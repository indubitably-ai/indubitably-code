import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools_playwright_mcp as tool


class DummyPage:
    def __init__(self):
        self.operations = []

    def goto(self, url, wait_until=None, timeout=None):
        self.operations.append(("goto", url, wait_until, timeout))

    def wait_for_selector(self, selector, **kwargs):
        self.operations.append(("wait", selector, kwargs))

    def screenshot(self, path, full_page=True):
        self.operations.append(("screenshot", path, full_page))
        Path(path).write_bytes(b"fake")

    def content(self):
        return "<html><body>Hello</body></html>"

    def evaluate(self, script):
        self.operations.append(("evaluate", script))
        if script.startswith("() =>"):
            return {"wrapped": True, "script": script}
        return {"wrapped": False, "script": script}


class DummyContext:
    def __init__(self, page):
        self.page = page

    def new_page(self):
        return self.page

    def close(self):
        self.page.operations.append(("context_close",))


class DummyBrowser:
    def __init__(self, page):
        self.page = page

    def new_context(self, **kwargs):
        self.page.operations.append(("new_context", kwargs))
        return DummyContext(self.page)

    def close(self):
        self.page.operations.append(("browser_close",))


class DummyPlaywright:
    def __init__(self, browser):
        self.chromium = SimpleNamespace(launch=lambda headless=True: browser)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        pass


def test_missing_playwright(monkeypatch):
    monkeypatch.setattr(tool, "_load_playwright", lambda: (_ for _ in ()).throw(RuntimeError("missing")))

    with pytest.raises(RuntimeError):
        tool.playwright_mcp_impl({"action": "navigate_and_screenshot", "url": "https://example.com"})


def test_screenshot_flow(monkeypatch, tmp_path):
    page = DummyPage()
    browser = DummyBrowser(page)

    def fake_loader():
        return lambda: DummyPlaywright(browser)

    monkeypatch.setattr(tool, "_load_playwright", fake_loader)

    result = json.loads(
        tool.playwright_mcp_impl(
            {
                "action": "navigate_and_screenshot",
                "url": "https://example.com",
                "wait_for_selector": "#app",
                "screenshot_path": str(tmp_path / "shot.png"),
                "return_screenshot_base64": False,
            }
        )
    )

    assert result["action"] == "navigate_and_screenshot"
    assert result["url"] == "https://example.com"
    assert result["screenshot_path"].endswith("shot.png")
    assert (tmp_path / "shot.png").exists()
    assert ("screenshot", str((tmp_path / "shot.png").resolve()), True) in page.operations


def test_screenshot_ascii_preview(monkeypatch, tmp_path):
    page = DummyPage()
    browser = DummyBrowser(page)

    def fake_loader():
        return lambda: DummyPlaywright(browser)

    monkeypatch.setattr(tool, "_load_playwright", fake_loader)
    monkeypatch.setattr(tool, "_generate_ascii_preview", lambda path, width=80: "ASCII")

    result = json.loads(
        tool.playwright_mcp_impl(
            {
                "action": "navigate_and_screenshot",
                "url": "https://example.com",
                "ascii_preview": True,
            }
        )
    )

    assert result["ascii_preview"] == "ASCII"


def test_get_content(monkeypatch):
    page = DummyPage()
    browser = DummyBrowser(page)

    monkeypatch.setattr(tool, "_load_playwright", lambda: (lambda: DummyPlaywright(browser)))

    payload = {
        "action": "get_content",
        "url": "https://example.com",
    }
    result = json.loads(tool.playwright_mcp_impl(payload))
    assert result["action"] == "get_content"
    assert "Hello" in result["content_sample"]
    assert ("goto", "https://example.com", "load", None) in page.operations


def test_evaluate_script(monkeypatch):
    page = DummyPage()
    browser = DummyBrowser(page)

    monkeypatch.setattr(tool, "_load_playwright", lambda: (lambda: DummyPlaywright(browser)))

    payload = {
        "action": "evaluate_script",
        "url": "https://example.com",
        "script": "() => document.title",
        "script_result_json": True,
    }
    result = json.loads(tool.playwright_mcp_impl(payload))
    assert result["result"]["script"] == "() => document.title"
    assert ("evaluate", "() => document.title") in page.operations


def test_evaluate_expression_wrapping(monkeypatch):
    page = DummyPage()
    browser = DummyBrowser(page)

    monkeypatch.setattr(tool, "_load_playwright", lambda: (lambda: DummyPlaywright(browser)))

    payload = {
        "action": "evaluate_script",
        "url": "https://example.com",
        "script": "return document.title;",
        "script_result_json": True,
    }
    result = json.loads(tool.playwright_mcp_impl(payload))
    assert result["result"]["script"].startswith("() =>")
    assert any(
        op[0] == "evaluate" and op[1].startswith("() =>") and "document.title" in op[1]
        for op in page.operations
    )
