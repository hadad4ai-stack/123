from __future__ import annotations
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from pathlib import Path
import re, json
from typing import Any
from x1_all_tools.registry import ToolSpec, object_schema
from x1_all_tools.security import safe_join

def _require_http(url: str) -> str:
    if not isinstance(url, str) or not re.match(r"^https?://", url, re.I):
        raise ValueError("Only http:// and https:// URLs are allowed")
    return url

class TitleTextLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title_parts = []
        self.text_parts = []
        self.links = []
        self._href = None
        self._link_text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() == "title":
            self.in_title = True
        if tag.lower() == "a" and attrs.get("href"):
            self._href = attrs.get("href")
            self._link_text = []

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.in_title = False
        if tag.lower() == "a" and self._href:
            text = " ".join(" ".join(self._link_text).split())
            self.links.append({"text": text, "href": self._href})
            self._href = None
            self._link_text = []

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data.strip())
        if self._href:
            self._link_text.append(data)
        if data.strip():
            self.text_parts.append(data.strip())

    @property
    def title(self):
        return " ".join(p for p in self.title_parts if p).strip()

    @property
    def text(self):
        return "\n".join(self.text_parts)

class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self._form = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        tag = tag.lower()
        if tag == "form":
            self._form = {"method": attrs.get("method", "get").lower(), "action": attrs.get("action", ""), "inputs": []}
        elif self._form is not None and tag in ("input", "textarea", "select"):
            self._form["inputs"].append({"tag": tag, "name": attrs.get("name", ""), "type": attrs.get("type", "text"), "value": attrs.get("value", "")})

    def handle_endtag(self, tag):
        if tag.lower() == "form" and self._form is not None:
            self.forms.append(self._form)
            self._form = None

def fetch_url(url: str, max_chars: int = 50000, timeout_seconds: int = 15, method: str = "GET", data: dict[str, Any] | None = None, headers: dict[str, str] | None = None, runtime=None) -> dict[str, Any]:
    _require_http(url)
    body = None
    final_headers = {"User-Agent": "X1AllTools/1.0"}
    if headers:
        final_headers.update({str(k): str(v) for k, v in headers.items()})
    if data is not None:
        encoded = urlencode({str(k): str(v) for k, v in data.items()}).encode("utf-8")
        body = encoded
        final_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = Request(url, data=body, headers=final_headers, method=method.upper())
    with urlopen(req, timeout=timeout_seconds) as res:
        raw = res.read(max_chars + 1)
        ctype = res.headers.get("Content-Type", "")
        final_url = res.geturl()
        status = getattr(res, "status", None)
    text = raw.decode("utf-8", errors="replace")
    parser = TitleTextLinkParser()
    if "html" in ctype.lower() or text.lstrip().startswith("<"):
        parser.feed(text[:max_chars])
    return {"url": final_url, "status": status, "content_type": ctype, "title": parser.title, "text": text[:max_chars], "truncated": len(raw) > max_chars}

def extract_links(url: str, max_links: int = 50, runtime=None) -> dict[str, Any]:
    page = fetch_url(url, max_chars=100000, runtime=runtime)
    parser = TitleTextLinkParser()
    parser.feed(page["text"])
    links = []
    for item in parser.links:
        href = urljoin(page["url"], item["href"])
        if href.startswith(("http://", "https://")):
            links.append({"title": item["text"][:200], "url": href})
        if len(links) >= max_links:
            break
    return {"url": page["url"], "links": links}

def search(query: str, max_results: int = 10, runtime=None) -> dict[str, Any]:
    url = "https://duckduckgo.com/html/?" + urlencode({"q": query})
    page = fetch_url(url, max_chars=120000, runtime=runtime)
    parser = TitleTextLinkParser()
    parser.feed(page["text"])
    results = []
    seen = set()
    for link in parser.links:
        href = link["href"]
        text = re.sub(r"\s+", " ", link["text"]).strip()
        if not href.startswith(("http://", "https://")):
            continue
        if "duckduckgo.com" in href:
            continue
        if (text, href) in seen:
            continue
        seen.add((text, href))
        results.append({"title": text[:200], "url": href})
        if len(results) >= max_results:
            break
    return {"query": query, "results": results, "source": "duckduckgo_html"}

def _pages(runtime):
    return runtime.state.setdefault("browser.pages", {})

def browser_open(url: str, max_chars: int = 100000, runtime=None) -> dict[str, Any]:
    page = fetch_url(url, max_chars=max_chars, runtime=runtime)
    parser = TitleTextLinkParser()
    parser.feed(page["text"])
    sid = runtime.new_id("page")
    links = [{"index": i, "title": l["text"][:200], "url": urljoin(page["url"], l["href"])} for i, l in enumerate(parser.links)]
    _pages(runtime)[sid] = {"url": page["url"], "html": page["text"], "text": parser.text, "title": parser.title, "links": links, "fields": {}}
    return {"page_id": sid, "url": page["url"], "title": parser.title, "links": links[:50]}

def browser_click(page_id: str, link_index: int | None = None, text: str | None = None, runtime=None) -> dict[str, Any]:
    pages = _pages(runtime)
    if page_id not in pages:
        raise KeyError(f"unknown browser page: {page_id}")
    page = pages[page_id]
    target = None
    if link_index is not None:
        target = page["links"][link_index]["url"]
    elif text is not None:
        for link in page["links"]:
            if text.lower() in link["title"].lower():
                target = link["url"]
                break
    if not target:
        raise ValueError("No matching link found")
    return browser_open(target, runtime=runtime)

def browser_type(page_id: str, field: str, value: str, runtime=None) -> dict[str, Any]:
    pages = _pages(runtime)
    if page_id not in pages:
        raise KeyError(f"unknown browser page: {page_id}")
    pages[page_id].setdefault("fields", {})[field] = value
    return {"page_id": page_id, "field": field, "value": value, "stored": True}

def browser_extract_text(page_id: str | None = None, url: str | None = None, runtime=None) -> dict[str, Any]:
    if url:
        opened = browser_open(url, runtime=runtime)
        page_id = opened["page_id"]
    pages = _pages(runtime)
    if page_id not in pages:
        raise KeyError(f"unknown browser page: {page_id}")
    page = pages[page_id]
    return {"page_id": page_id, "url": page["url"], "title": page["title"], "text": page["text"]}

def browser_download(url: str, path: str, timeout_seconds: int = 30, runtime=None) -> dict[str, Any]:
    _require_http(url)
    target = safe_join(runtime.workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    req = Request(url, headers={"User-Agent": "X1AllTools/1.0"})
    with urlopen(req, timeout=timeout_seconds) as res:
        data = res.read()
        ctype = res.headers.get("Content-Type", "")
        final_url = res.geturl()
    target.write_bytes(data)
    return {"url": final_url, "path": str(target), "bytes": target.stat().st_size, "content_type": ctype}

def browser_fill_form(page_id: str, fields: dict[str, Any], form_index: int = 0, runtime=None) -> dict[str, Any]:
    pages = _pages(runtime)
    if page_id not in pages:
        raise KeyError(f"unknown browser page: {page_id}")
    page = pages[page_id]
    fp = FormParser()
    fp.feed(page["html"])
    if form_index >= len(fp.forms):
        raise ValueError("form_index out of range")
    form = fp.forms[form_index]
    action = urljoin(page["url"], form.get("action") or page["url"])
    method = (form.get("method") or "get").lower()
    payload = {}
    for inp in form["inputs"]:
        if inp.get("name"):
            payload[inp["name"]] = inp.get("value", "")
    payload.update({str(k): str(v) for k, v in fields.items()})
    if method == "get":
        sep = "&" if "?" in action else "?"
        return browser_open(action + sep + urlencode(payload), runtime=runtime)
    page2 = fetch_url(action, method="POST", data=payload, runtime=runtime)
    sid = runtime.new_id("page")
    parser = TitleTextLinkParser(); parser.feed(page2["text"])
    _pages(runtime)[sid] = {"url": page2["url"], "html": page2["text"], "text": parser.text, "title": parser.title, "links": [], "fields": {}}
    return {"page_id": sid, "url": page2["url"], "title": parser.title, "submitted": True}

def browser_screenshot(url: str, path: str = "screenshot.png", full_page: bool = True, runtime=None) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("browser.screenshot requires Playwright: pip install playwright && playwright install chromium") from exc
    target = safe_join(runtime.workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        page.screenshot(path=str(target), full_page=full_page)
        title = page.title()
        browser.close()
    return {"url": url, "path": str(target), "title": title, "bytes": target.stat().st_size}

TOOLS = [
    ToolSpec("web.search", "Search the web using a lightweight DuckDuckGo HTML adapter.", object_schema({"query": {"type": "string"}, "max_results": {"type": "integer", "default": 10}}, ["query"]), search),
    ToolSpec("web.fetch_url", "Fetch a URL and return text/HTML.", object_schema({"url": {"type": "string"}, "max_chars": {"type": "integer", "default": 50000}, "timeout_seconds": {"type": "integer", "default": 15}, "method": {"type": "string", "default": "GET"}, "data": {"type": ["object", "null"], "default": None}, "headers": {"type": ["object", "null"], "default": None}}, ["url"]), fetch_url),
    ToolSpec("web.extract_links", "Extract links from a URL.", object_schema({"url": {"type": "string"}, "max_links": {"type": "integer", "default": 50}}, ["url"]), extract_links),
    ToolSpec("browser.open", "Open/fetch a web page and store a lightweight browser page state.", object_schema({"url": {"type": "string"}, "max_chars": {"type": "integer", "default": 100000}}, ["url"]), browser_open),
    ToolSpec("browser.click", "Open a link from a stored browser page by index or text.", object_schema({"page_id": {"type": "string"}, "link_index": {"type": ["integer", "null"], "default": None}, "text": {"type": ["string", "null"], "default": None}}, ["page_id"]), browser_click),
    ToolSpec("browser.type", "Store a field value in a lightweight browser page state.", object_schema({"page_id": {"type": "string"}, "field": {"type": "string"}, "value": {"type": "string"}}, ["page_id", "field", "value"]), browser_type),
    ToolSpec("browser.screenshot", "Take a real browser screenshot using Playwright if installed.", object_schema({"url": {"type": "string"}, "path": {"type": "string", "default": "screenshot.png"}, "full_page": {"type": "boolean", "default": True}}, ["url"]), browser_screenshot),
    ToolSpec("browser.extract_text", "Extract text from a stored page or URL.", object_schema({"page_id": {"type": ["string", "null"], "default": None}, "url": {"type": ["string", "null"], "default": None}}, []), browser_extract_text),
    ToolSpec("browser.download", "Download a URL to workspace.", object_schema({"url": {"type": "string"}, "path": {"type": "string"}, "timeout_seconds": {"type": "integer", "default": 30}}, ["url", "path"]), browser_download),
    ToolSpec("browser.fill_form", "Fill and submit a simple HTML form.", object_schema({"page_id": {"type": "string"}, "fields": {"type": "object"}, "form_index": {"type": "integer", "default": 0}}, ["page_id", "fields"]), browser_fill_form),
]
