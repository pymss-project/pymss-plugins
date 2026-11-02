"""Verify duration controls with both algorithms and streamed task progress."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from tool_views_smoke import ROOT, complete, fill_audio, open_tool, select, server_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url")
    parser.add_argument("--artifacts", type=Path, default=ROOT / "tooling/.tmp/timing-algorithms")
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    snapshot = json.loads((ROOT / "plugins/timing/operations.json").read_text(encoding="utf-8"))
    with server_url(args.url) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-proxy-server"])
        try:
            for dark, width in [(False, 1100), (True, 420)]:
                page, tool = open_tool(browser, base, "timing", snapshot["operations"], dark=dark, width=width)
                page.wait_for_load_state("networkidle")
                expect(tool.locator("#operation")).to_have_count(0)
                expect(tool.locator("#param-algorithm")).to_contain_text("Rubber Band")
                duration = tool.locator("#param-duration_percent input")
                expect(tool.locator('label[for="param-duration_percent"]')).to_have_text("时长（%）")
                expect(duration).to_be_enabled()
                duration.fill("140")
                duration.press("Tab")
                select(tool, "#param-algorithm", "Radius（音质优先，较慢）")
                expect(duration).to_have_value("140")
                expect(duration).to_be_enabled()
                duration.fill("50")
                duration.press("Tab")
                fill_audio(tool)
                tool.locator("#param-n_steps input").fill("3")
                tool.locator("#param-n_steps input").press("Tab")
                expect(tool.locator(".n-base-select-option:visible")).to_have_count(0)
                page.screenshot(path=str(args.artifacts / f"radius-editable-{width}.png"), full_page=True)
                tool.locator("#run").click()
                page.wait_for_function("bridge.active!==null")
                request = page.evaluate("bridge.active")
                assert request["params"]["operation"] == "pymss.timing.process", request
                assert request["params"]["params"] == {"algorithm": "radius", "n_steps": 3, "duration_percent": 50}, request
                page.evaluate("""() => document.querySelector('#plugin').contentWindow.postMessage({
                    jsonrpc:'2.0',method:'task.progress',params:{
                        id:bridge.active.id,operation:bridge.active.params.operation,fraction:0.42,message:'Processing audio (Radius)'
                }},'*')""")
                tool.locator(".tool-log-button").click()
                expect(tool.locator("#progress")).to_be_visible()
                expect(tool.locator(".operation-detail").filter(has_text="42%")).to_be_visible()
                page.screenshot(path=str(args.artifacts / f"radius-progress-{width}.png"), full_page=True)
                complete(page, {"audio": {"kind": "audio_file", "path": "/output/pitched.wav"}})
                expect(tool.locator("#run")).to_be_enabled()
                page.keyboard.press("Escape")
                page.evaluate("bridge.active=null")
                select(tool, "#param-algorithm", "Rubber Band（较快）")
                expect(duration).to_be_enabled()
                expect(duration).to_have_value("50")
                duration.fill("200")
                duration.press("Tab")
                page.screenshot(path=str(args.artifacts / f"rubberband-editable-{width}.png"), full_page=True)
                tool.locator("#run").click()
                page.wait_for_function("bridge.active!==null")
                request = page.evaluate("bridge.active")
                assert request["params"]["params"] == {"algorithm": "rubberband", "n_steps": 3, "duration_percent": 200}, request
                complete(page, {"audio": {"kind": "audio_file", "path": "/output/processed.wav"}})
                expect(tool.locator("#run")).to_be_enabled()
                page.close()
            print(json.dumps({"radiusDuration": "50%, editable", "rubberbandDuration": "200%, editable", "progress": "42%", "themes": 2}))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
