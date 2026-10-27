"""Self-check for the web screenshot OCR tool: render Chinese text in Chromium, OCR it back.

No network: the page is set from a local HTML string, exactly as web_capture renders its snapshot.

    .venv/bin/python -m scripts.check_web_ocr          # reads the env file like the backend does
    AI_JUEJIN_ENV_FILE=.env.deepseek .venv/bin/python -m scripts.check_web_ocr

Each failure names the setup step to redo (scripts/setup_web_ocr.sh).
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

from config.ai_conf import settings
from harness.web_capture import browser_launch_env

SAMPLE = "织密新就业群体保障网"
PAGE = f"<html><body style='font-size:40px;padding:40px'><p>{SAMPLE}</p><p>2026年6月7日 经济日报</p></body></html>"


async def _screenshot(path: Path) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, **browser_launch_env())
        try:
            page = await browser.new_page(viewport={"width": 900, "height": 400})
            await page.set_content(PAGE)
            await page.screenshot(path=str(path))
        finally:
            await browser.close()


async def main() -> int:
    print(f"WEB_CAPTURE_LIBRARY_PATH={settings.web_capture_library_path or '(unset)'}")
    print(f"OCR_ENABLE_MKLDNN={settings.ocr_enable_mkldnn}")
    try:
        import playwright  # noqa: F401
        import paddleocr  # noqa: F401
    except ImportError as exc:
        print(f"FAIL packages: {exc}. Run scripts/setup_web_ocr.sh (step: OCR Python packages).")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        image = Path(tmp) / "check.png"
        try:
            await _screenshot(image)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL browser: {str(exc).splitlines()[0][:300]}")
            print("  Missing shared libraries -> set WEB_CAPTURE_LIBRARY_PATH as printed by scripts/setup_web_ocr.sh;")
            print("  'Executable doesn't exist' -> python -m playwright install chromium-headless-shell.")
            return 1
        print("OK   browser screenshot")

        from mcp_servers.web_server import _get_ocr_provider

        start = time.perf_counter()
        try:
            result = await _get_ocr_provider(settings.ocr_provider_name).extract(str(image))
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL ocr: {type(exc).__name__}: {str(exc)[:300]}")
            print("  A oneDNN / PIR error on PaddlePaddle 3.x CPU -> OCR_ENABLE_MKLDNN=false.")
            return 1
        text = "".join(str(getattr(result, "text", "") or "").split())
        print(f"OCR  {time.perf_counter() - start:.1f}s: {text[:60]}")
        if SAMPLE not in text:
            print("FAIL ocr text: Chinese was not recognized. Boxes or digits instead of characters mean")
            print("  no CJK font is installed -> rerun scripts/setup_web_ocr.sh (step: CJK fonts).")
            return 1
    print("OK   web OCR works")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
