"""Playwright MCP-inspired tool for browser automation tasks.

This mirrors the capabilities of the Playwright MCP server by exposing common
browser automation flows (navigation, screenshots, DOM extraction, script
execution) through a structured tool interface the agent can call.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List


def playwright_mcp_tool_def() -> dict:
    return {
        "name": "playwright_mcp",
        "description": (
            "Automate a headless Playwright browser session using a simplified MCP-inspired interface. Choose an `action`: 'navigate_and_screenshot' loads a page and captures an image, 'get_content' fetches HTML/text, and 'evaluate_script' runs a JavaScript snippet. "
            "You can specify `url`, tune navigation waits with `wait_until`/`wait_for_selector`/`wait_timeout_ms`, configure headers or viewport, and control screenshots via `screenshot_path`, `full_page`, `return_screenshot_base64`, and `ascii_preview`. Script actions accept `script` plus an optional `script_result_json` toggle, "
            "while all actions can select a browser engine and headless mode. Example: to snapshot a login page after ensuring the form is visible, call navigate_and_screenshot with wait_for_selector='#login'. Avoid using this tool for authenticated flows that require complex multi-step interactions (build a dedicated automation instead), "
            "for extremely long-running crawls (there is no background mode), or when simpler HTTP fetching via requests would suffice."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "navigate_and_screenshot",
                        "get_content",
                        "evaluate_script",
                    ],
                    "description": "High-level browser automation action to perform.",
                },
                "url": {
                    "type": "string",
                    "description": "Target URL to open in the browser.",
                },
                "wait_until": {
                    "type": "string",
                    "enum": ["load", "domcontentloaded", "networkidle", "commit"],
                    "description": "Pass-through for Playwright's wait_until parameter when navigating.",
                },
                "wait_for_selector": {
                    "type": "string",
                    "description": "Optional CSS selector to wait for before proceeding.",
                },
                "wait_timeout_ms": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Timeout in milliseconds when waiting for selectors or navigation.",
                },
                "headers": {
                    "type": "object",
                    "description": "Optional request headers to set on the page context.",
                },
                "viewport": {
                    "type": "object",
                    "properties": {
                        "width": {"type": "integer", "minimum": 100},
                        "height": {"type": "integer", "minimum": 100},
                    },
                    "additionalProperties": False,
                    "description": "Viewport dimensions for the browser context.",
                },
                "screenshot_path": {
                    "type": "string",
                    "description": "Optional path for storing the screenshot.",
                },
                "full_page": {
                    "type": "boolean",
                    "description": "Capture the full page instead of the viewport when taking screenshots.",
                },
                "return_screenshot_base64": {
                    "type": "boolean",
                    "description": "If true, include a base64 encoded version of the screenshot in the response.",
                },
                "ascii_preview": {
                    "type": "boolean",
                    "description": "Generate a small ASCII art preview of screenshots for terminal output.",
                },
                "script": {
                    "type": "string",
                    "description": "JavaScript snippet to evaluate in the page context.",
                },
                "script_result_json": {
                    "type": "boolean",
                    "description": "Attempt to JSON serialize script evaluation results (default true).",
                },
                "browser": {
                    "type": "string",
                    "enum": ["chromium", "firefox", "webkit"],
                    "description": "Browser engine to use (default chromium).",
                },
                "headless": {
                    "type": "boolean",
                    "description": "Launch browser in headless mode (default true).",
                },
            },
            "required": ["action"],
        },
    }


def playwright_mcp_impl(payload: Dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise ValueError("Input payload must be an object")

    action = payload.get("action")
    if action not in {"navigate_and_screenshot", "get_content", "evaluate_script"}:
        raise ValueError("Unsupported action; choose navigate_and_screenshot, get_content, or evaluate_script")

    sync_playwright = _load_playwright()

    wait_options = _extract_wait_options(payload)
    headers = payload.get("headers")
    viewport = payload.get("viewport")
    browser_name = payload.get("browser") or "chromium"
    headless = True if payload.get("headless") is None else bool(payload["headless"])

    with sync_playwright() as p:
        browser_type = getattr(p, browser_name, None)
        if browser_type is None:
            raise ValueError(f"Unsupported browser '{browser_name}'")
        browser = browser_type.launch(headless=headless)
        context_kwargs: Dict[str, Any] = {}
        if headers:
            if not isinstance(headers, dict):
                raise ValueError("headers must be an object mapping header names to values")
            context_kwargs["extra_http_headers"] = {str(k): str(v) for k, v in headers.items()}
        if viewport:
            if not isinstance(viewport, dict) or "width" not in viewport or "height" not in viewport:
                raise ValueError("viewport must include width and height")
            context_kwargs["viewport"] = {"width": int(viewport["width"]), "height": int(viewport["height"])}
        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        try:
            if action == "navigate_and_screenshot":
                result = _handle_screenshot_action(page, payload, wait_options)
            elif action == "get_content":
                result = _handle_get_content(page, payload, wait_options)
            else:
                result = _handle_evaluate(page, payload, wait_options)
        finally:
            context.close()
            browser.close()

    return json.dumps(result, ensure_ascii=False, indent=2)


def _handle_screenshot_action(page: Any, payload: Dict[str, Any], wait_options: Dict[str, Any]) -> Dict[str, Any]:
    url = payload.get("url")
    if not url:
        raise ValueError("navigate_and_screenshot requires a url")

    _navigate(page, url, wait_options)

    should_wait_selector = payload.get("wait_for_selector")
    if should_wait_selector:
        page.wait_for_selector(should_wait_selector, **wait_options)

    full_page = True if payload.get("full_page") is None else bool(payload["full_page"])
    screenshot_path = payload.get("screenshot_path")
    base_dir = Path("run_artifacts/playwright")
    base_dir.mkdir(parents=True, exist_ok=True)
    if screenshot_path:
        path = Path(screenshot_path)
        if not path.is_absolute():
            path = base_dir / path
    else:
        fd, tmp_path = tempfile.mkstemp(prefix="screenshot_", suffix=".png", dir=base_dir)
        os.close(fd)
        path = Path(tmp_path)

    page.screenshot(path=str(path), full_page=full_page)

    result: Dict[str, Any] = {
        "action": "navigate_and_screenshot",
        "url": url,
        "screenshot_path": str(path.resolve()),
    }

    if payload.get("return_screenshot_base64"):
        with path.open("rb") as fh:
            result["screenshot_base64"] = base64.b64encode(fh.read()).decode("utf-8")

    if payload.get("ascii_preview"):
        result["ascii_preview"] = _generate_ascii_preview(path)

    return result


def _handle_get_content(page: Any, payload: Dict[str, Any], wait_options: Dict[str, Any]) -> Dict[str, Any]:
    url = payload.get("url")
    if not url:
        raise ValueError("get_content requires a url")

    _navigate(page, url, wait_options)

    selector = payload.get("wait_for_selector")
    if selector:
        page.wait_for_selector(selector, **wait_options)

    content = page.content()
    sample = content[:2000] + ("…" if len(content) > 2000 else "")
    return {
        "action": "get_content",
        "url": url,
        "content_sample": sample,
    }


def _handle_evaluate(page: Any, payload: Dict[str, Any], wait_options: Dict[str, Any]) -> Dict[str, Any]:
    url = payload.get("url")
    if not url:
        raise ValueError("evaluate_script requires a url")
    script = payload.get("script")
    if not script:
        raise ValueError("evaluate_script requires a script to run")

    _navigate(page, url, wait_options)

    selector = payload.get("wait_for_selector")
    if selector:
        page.wait_for_selector(selector, **wait_options)

    prepared_script = _prepare_evaluate_script(script)

    result_value = page.evaluate(prepared_script)
    if payload.get("script_result_json", True):
        try:
            result_serialized = json.loads(json.dumps(result_value, default=str))
        except TypeError:
            result_serialized = str(result_value)
    else:
        result_serialized = result_value

    return {
        "action": "evaluate_script",
        "url": url,
        "result": result_serialized,
    }


def _navigate(page: Any, url: str, wait_options: Dict[str, Any]) -> None:
    wait_until = wait_options.get("wait_until")
    timeout = wait_options.get("timeout")
    page.goto(url, wait_until=wait_until, timeout=timeout)


def _extract_wait_options(payload: Dict[str, Any]) -> Dict[str, Any]:
    wait_until = payload.get("wait_until") or "load"
    timeout_ms = payload.get("wait_timeout_ms")
    wait_opts: Dict[str, Any] = {"wait_until": wait_until}
    if timeout_ms is not None:
        wait_opts["timeout"] = int(timeout_ms)
    return wait_opts


def _load_playwright():
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on optional dep
        raise RuntimeError(
            "Playwright is not installed. Install the 'playwright' package and run 'playwright install'."
        ) from exc
    return sync_playwright


def _prepare_evaluate_script(script: str) -> str:
    trimmed = script.strip()
    if not trimmed:
        raise ValueError("Script must not be empty")

    lowered = trimmed.lstrip().lower()
    if trimmed.startswith("(") or trimmed.startswith("async ") or trimmed.startswith("function "):
        return trimmed

    if "=>" in trimmed.split("\n", 1)[0]:
        return trimmed

    if "\n" in trimmed or ";" in trimmed or lowered.startswith("return"):
        return f"() => {{ {trimmed} }}"

    return f"() => ({trimmed})"


def _generate_ascii_preview(path: Path, width: int = 80) -> str:
    try:
        from PIL import Image  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional feature
        raise RuntimeError(
            "ASCII preview requested but Pillow is not installed. Run 'uv add pillow'."
        ) from exc

    if width <= 0:
        width = 80

    charset = " .:-=+*#%@"
    try:
        with Image.open(path) as img:
            img = img.convert("L")
            aspect_ratio = img.height / img.width if img.width else 1
            height = max(1, int(width * aspect_ratio * 0.55))
            img = img.resize((width, height))
            pixels = img.getdata()
    except Exception as exc:  # pragma: no cover - depends on optional dep
        raise RuntimeError(f"Failed to generate ASCII preview: {exc}") from exc

    lines = []
    scale = len(charset) - 1
    for y in range(height):
        row = ""
        for x in range(width):
            value = pixels[y * width + x]
            row += charset[min(scale, int(value / 255 * scale))]
        lines.append(row)
    return "\n".join(lines)
