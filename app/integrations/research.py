"""Bounded web evidence. DNS addresses are pinned to prevent redirect/rebinding SSRF."""

import ipaddress
import socket
import ssl
import urllib.parse
from html.parser import HTMLParser

from ddgs import DDGS

from app.domain.contracts import Source

MAX_BYTES = 256_000


def public_addresses(host):
    addresses = list(
        dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
    )
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Research can only access public internet hosts")
    return addresses


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "noscript"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "noscript") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def fetch_text(url: str) -> str:
    # Custom TLS connection pins the validated IP but authenticates the original host.
    import http.client

    for _ in range(4):
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise ValueError("Only public HTTPS pages on port 443 are supported")
        host = parsed.hostname.encode("idna").decode()
        address = public_addresses(host)[0]
        connection = http.client.HTTPSConnection(host, timeout=8, context=ssl.create_default_context())
        connection._create_connection = lambda target, timeout, source_address=None, **kw: (
            socket.create_connection((address, 443), timeout, source_address)
        )
        try:
            connection.request(
                "GET",
                urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, "")),
                headers={"User-Agent": "PredestinationResearch/1.0", "Accept": "text/html,text/plain"},
            )
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                url = urllib.parse.urljoin(url, response.getheader("Location", ""))
                continue
            if response.status != 200 or not any(
                t in response.getheader("Content-Type", "") for t in ("text/html", "text/plain")
            ):
                return ""
            payload = response.read(MAX_BYTES + 1)
            if len(payload) > MAX_BYTES:
                return ""
            parser = TextParser()
            parser.feed(payload.decode("utf-8", errors="replace"))
            return " ".join(" ".join(parser.parts).split())[:12000]
        finally:
            connection.close()
    return ""


def research(queries: list[str]) -> dict:
    sources, failures = [], []
    seen = set()
    for query in queries[:3]:
        try:
            hits = DDGS(timeout=8).text(query[:300], max_results=3, backend="duckduckgo")
            for item in hits:
                url = item.get("href") or item.get("url")
                if not url or url in seen or len(sources) >= 3:
                    continue
                seen.add(url)
                try:
                    text = fetch_text(url)
                    if text:
                        sources.append(
                            Source(
                                url=url, title=str(item.get("title", ""))[:240], excerpt=text[:4000]
                            ).model_dump()
                        )
                except Exception:
                    failures.append("A search result could not be retrieved safely.")
        except Exception:
            failures.append("Free web search is temporarily unavailable.")
    return {"sources": sources, "limitations": list(dict.fromkeys(failures))}
