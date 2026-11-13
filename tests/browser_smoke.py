"""Optional real-browser smoke test against an isolated running development app.

Run: python tests/browser_smoke.py --base-url http://127.0.0.1:8001
Uses installed Edge by default; set BROWSER_CHANNEL=chromium after playwright install chromium.
"""

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

FAKE_SPEECH = """
window.SpeechRecognition = window.webkitSpeechRecognition = class {
  start() { setTimeout(() => this.onstart && this.onstart(), 10); }
  stop() {
    setTimeout(() => {
      const result = Object.assign([{ transcript: 'add a study group tomorrow at 6 pm' }], { isFinal: true });
      if (this.onresult) this.onresult({ resultIndex: 0, results: [result] });
      if (this.onend) this.onend();
    }, 20);
  }
  abort() { if (this.onend) this.onend(); }
};
// Record what the assistant says instead of playing audio.
window.__spoken = [];
const fakeSynth = {
  getVoices: () => [],
  cancel: () => {},
  speak: utterance => { window.__spoken.push(utterance.text); setTimeout(() => utterance.onend && utterance.onend(), 10); },
};
Object.defineProperty(window, 'speechSynthesis', { value: fakeSynth, configurable: true });
"""


def main(base):
    errors = []
    with sync_playwright() as runner:
        browser = runner.chromium.launch(channel=os.getenv("BROWSER_CHANNEL", "msedge"), headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))
        # A scripted stand-in for the browser's speech engine, so voice is tested without a microphone.
        page.add_init_script(FAKE_SPEECH)
        page.goto(base + "/home", wait_until="domcontentloaded")
        page.locator("#auth-email").fill(f"smoke-{uuid4().hex[:12]}@example.com")
        page.locator("#auth-password").fill("Smoke-test-password123")
        page.locator("#auth-signup-btn").click()
        page.wait_for_url(base + "/")
        expect(page.locator(".timezone-control button")).to_be_visible()
        expect(page.locator("#gcal-conn-btn")).to_be_hidden()
        # First sign-in asks for the timezone in an accessible dialog (not a free-text prompt).
        expect(page.locator("#tz-dialog")).to_be_visible()
        page.locator("#tz-select").select_option("UTC")
        page.locator("#tz-save").click()
        expect(page.locator("#tz-dialog")).not_to_be_visible()
        page.wait_for_function("typeof currentUser !== 'undefined' && currentUser.timezone_confirmed")
        page.locator("#quick-text").fill("Browser meeting on 2030-01-01 at 8 am for 45 minutes")
        page.locator("#quick-manual").click()
        expect(page.locator("#quick-dialog")).to_be_visible()
        page.locator("#quick-period").select_option("AM")
        page.locator("#quick-duration").fill("45")
        page.locator("#quick-save").click()
        expect(page.locator("#quick-dialog")).not_to_be_visible()
        expect(page.locator("#month-view")).to_contain_text("Browser meeting")
        for view in ["week", "day", "month"]:
            page.locator('[data-view="' + view + '"]').click()
            expect(page.locator('[data-view="' + view + '"]')).to_have_attribute("aria-pressed", "true")
        theme = page.locator("html").get_attribute("data-theme")
        page.locator("#theme-toggle").click()
        assert page.locator("html").get_attribute("data-theme") != theme
        page.locator("#tools-toggle").click()
        expect(page.locator("#tools-panel")).to_be_visible()
        # Talking assistant: tap Talk, speak, the reply is shown and spoken; typing remains available.
        page.locator("#planner-tab").click()
        page.route(
            "**/api/voice/turn",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {"session_id": None, "say": "Sure, what time works?", "action": "none", "run": None}
                ),
            ),
        )
        mic = page.locator("#ai-mic")
        expect(mic).to_contain_text("Talk")
        mic.click()
        expect(mic).to_have_attribute("aria-pressed", "true")
        mic.click()
        expect(page.locator("#ai-chat-messages")).to_contain_text("add a study group tomorrow at 6 pm")
        expect(page.locator("#ai-chat-messages")).to_contain_text("Sure, what time works?")
        page.wait_for_function("window.__spoken.includes('Sure, what time works?')")
        expect(mic).to_have_attribute("aria-pressed", "false")
        page.unroute("**/api/voice/turn")
        page.locator("#tools-toggle").click()
        expect(page.locator("#tools-panel")).not_to_be_visible()
        page.reload(wait_until="domcontentloaded")
        # Mock only the async protocol here; PostgreSQL graph execution is covered
        # by test_agent_graph.py. This verifies polling and revision-bound UI actions.
        session_id = page.request.post(base + "/api/agent/new-session").json()["session_id"]
        state = {"approved": False}
        event = {
            "date": "2030-01-02",
            "start": "10:00",
            "end": "11:00",
            "label": "Reviewed event",
            "repeatDays": [],
        }

        def reply():
            if state["approved"]:
                return {
                    "run_id": "browser-contract",
                    "session_id": session_id,
                    "status": "completed",
                    "stage": "Completed",
                    "pending": {},
                    "result": {"response": "Browser approval contract checked"},
                    "draft": None,
                    "events": [],
                }
            return {
                "run_id": "browser-contract",
                "session_id": session_id,
                "status": "awaiting_approval",
                "stage": "Awaiting approval",
                "pending": {"interrupt_id": "browser-interrupt"},
                "result": {},
                "events": [],
                "draft": {
                    "id": "browser-draft",
                    "revision": "browser-revision",
                    "preview": {"changes": [{"kind": "create", "event": event}], "scheduled": [event]},
                },
            }

        def fulfill(route, value, status=200):
            route.fulfill(status=status, content_type="application/json", body=json.dumps(value))

        page.route(
            "**/api/agent/chat",
            lambda route: fulfill(
                route, {**reply(), "status": "queued", "stage": "Planning", "draft": None}, 202
            ),
        )
        page.route("**/api/agent/runs/browser-contract", lambda route: fulfill(route, reply()))
        page.route("**/api/agent/sessions/" + session_id + "/runs", lambda route: fulfill(route, [reply()]))

        def confirm(route):
            value = route.request.post_data_json
            assert value["draft_id"] == "browser-draft" and value["revision"] == "browser-revision"
            state["approved"] = True
            fulfill(route, reply(), 202)

        page.route("**/api/agent/confirm", confirm)
        page.locator("#quick-text").fill("UI contract test")
        page.locator("#quick-review").click()
        expect(page.get_by_role("button", name="Approve", exact=True)).to_be_visible()
        expect(page.locator("#ai-chat-messages")).to_contain_text("Not saved")
        expect(page.locator("#ai-chat-messages")).to_contain_text("1h")
        page.reload(wait_until="domcontentloaded")
        expect(page.get_by_role("button", name="Approve", exact=True)).to_be_visible()
        page.get_by_role("button", name="Approve", exact=True).click()
        expect(page.locator("#ai-chat-messages")).to_contain_text("Browser approval contract checked")
        Path("data").mkdir(exist_ok=True)
        page.screenshot(path="data/browser-smoke.png", full_page=True)
        assert not errors, errors
        browser.close()
    print(
        "Browser smoke passed: signup, timezone dialog, manual entry, views, themes, tools, voice, polling, reload recovery, approval protocol."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    main(parser.parse_args().base_url.rstrip("/"))
