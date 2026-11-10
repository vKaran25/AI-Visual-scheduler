"""Parse the actual extracted frontend and verify the async integration contract."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_scripts_parse_and_assets_resolve():
    if not shutil.which("node"):
        pytest.skip("Node.js required")
    for path in (ROOT / "frontend/assets/js").glob("*.js"):
        result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
    for filename in ["index.html", "landing.html"]:
        html = (ROOT / "frontend" / filename).read_text(encoding="utf-8")
        assert not re.search(r"<script>\s*\S", html)
        assert "<style>" not in html
        for asset in re.findall(r'(?:src|href)="(/assets/[^"]+)"', html):
            assert (ROOT / "frontend" / asset.lstrip("/")).exists(), asset


def test_ui_uses_resumable_runs_and_revision_bound_approval():
    agent = (ROOT / "frontend/assets/js/agent.js").read_text(encoding="utf-8")
    assert "/resume" in agent and "/retry" in agent and "/cancel" in agent
    assert "revision:run.draft.revision" in agent
    assert "setTimeout" in agent
    assert "textContent" in agent
    bootstrap = (ROOT / "frontend/assets/js/bootstrap.js").read_text()
    assert "window.API_BASE_URL = ''" in bootstrap
    config = (ROOT / "netlify.toml").read_text()
    assert config.index("/api/*") < config.index('from = "/*"')
