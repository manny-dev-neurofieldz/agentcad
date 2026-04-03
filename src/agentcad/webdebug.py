"""Headless browser debugging for HTML viewer pages.

Opens an HTML file in headless Chromium via Playwright, captures JS console
errors, and reports them. Used to validate that three.js, highlight.js,
and STL viewer components load correctly.

Usage:
    from agentcad.webdebug import check_html
    errors = check_html("/path/to/index.html")
    for e in errors:
        print(e)

CLI:
    agentcad check /path/to/index.html
"""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class ConsoleEntry:
    """A captured browser console message."""
    level: str  # "log", "warning", "error", "info"
    text: str
    url: str = ""
    line: int = 0


@dataclass
class CheckResult:
    """Result of checking an HTML page."""
    path: Path
    errors: List[ConsoleEntry] = field(default_factory=list)
    warnings: List[ConsoleEntry] = field(default_factory=list)
    logs: List[ConsoleEntry] = field(default_factory=list)
    page_error: str = ""
    success: bool = True

    def summary(self) -> str:
        lines = [f"Check: {self.path}"]
        if self.page_error:
            lines.append(f"  PAGE ERROR: {self.page_error}")
        if self.errors:
            lines.append(f"  {len(self.errors)} JS error(s):")
            for e in self.errors:
                lines.append(f"    [{e.level}] {e.text}")
                if e.url:
                    lines.append(f"           at {e.url}:{e.line}")
        if self.warnings:
            lines.append(f"  {len(self.warnings)} warning(s)")
        if not self.errors and not self.page_error:
            lines.append("  OK — no JS errors")
        return "\n".join(lines)


async def _check_async(html_path: Path, timeout_ms: int = 10000) -> CheckResult:
    """Open HTML in headless Chromium and capture console output."""
    from playwright.async_api import async_playwright

    result = CheckResult(path=html_path)
    url = html_path.resolve().as_uri()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        def on_console(msg):
            entry = ConsoleEntry(
                level=msg.type,
                text=msg.text,
                url=msg.location.get("url", "") if msg.location else "",
                line=msg.location.get("lineNumber", 0) if msg.location else 0,
            )
            if msg.type == "error":
                result.errors.append(entry)
                result.success = False
            elif msg.type == "warning":
                result.warnings.append(entry)
            else:
                result.logs.append(entry)

        def on_page_error(error):
            result.page_error = str(error)
            result.success = False

        page.on("console", on_console)
        page.on("pageerror", on_page_error)

        try:
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            # Give scripts a moment to finish
            await page.wait_for_timeout(2000)
        except Exception as e:
            result.page_error = str(e)
            result.success = False

        await browser.close()

    return result


def check_html(html_path: str | Path, timeout_ms: int = 10000) -> CheckResult:
    """Check an HTML file for JS console errors. Synchronous wrapper."""
    return asyncio.run(_check_async(Path(html_path), timeout_ms))
