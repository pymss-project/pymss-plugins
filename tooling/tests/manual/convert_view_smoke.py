"""Check the converter's component interface and its existing batch SDK contract."""

from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
from playwright.sync_api import expect, sync_playwright
from file_tool_views_smoke import ROOT, open_tool, server_url


def choose(frame, index, label):
    frame.locator(".n-select").nth(index).click()
    frame.locator(".n-base-select-option").filter(
        has_text=re.compile("^" + re.escape(label) + "$")
    ).click()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url")
    parser.add_argument("--artifacts", type=Path, default=ROOT / "tooling/.tmp/convert-view")
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    passed = []
    with server_url(args.url) as base, sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-proxy-server"])
        try:
            page, frame = open_tool(browser, base, "convert")
            try:
                expect(frame.locator(".audio-tool-card--main")).to_be_visible()
                expect(frame.locator(".audio-tool-card--side")).to_have_count(0)
                position = frame.locator(".audio-tool-header").evaluate(
                    "el => { const r=el.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2} }"
                )
                page.evaluate(
                    "position => document.getElementById('plugin').contentWindow.postMessage({jsonrpc:'2.0',method:'host.filesDrop',params:{type:'drop',position,paths:['/audio']}}, '*')",
                    position,
                )
                expect(frame.locator(".audio-tool-files > div")).to_have_count(2)
                assert page.evaluate(
                    "bridge.requests.some(x=>x.method==='files.scanAudio' && x.params.paths[0]==='/audio')"
                )
                passed.append("page-header-drop-imports-audio-folder")
                frame.get_by_role(
                    "button", name="Add more files", exact=True
                ).click()
                frame.get_by_role("button", name="Add input folder", exact=True).click()
                expect(frame.locator(".audio-tool-files > div")).to_have_count(2)
                choose(frame, 0, "OGG")
                choose(frame, 3, "450k")
                choose(frame, 0, "MP3")
                frame.locator(".n-select").nth(3).click()
                expect(
                    frame.locator(".n-base-select-option").filter(has_text="450k")
                ).to_have_count(0)
                page.keyboard.press("Escape")
                choose(frame, 0, "OGG")
                passed.append("folder-dedup-and-independent-codec-options")
                frame.locator(".audio-tool-actions button").click()
                page.wait_for_function(
                    "bridge.requests.some(x=>x.method==='operations.start')"
                )
                request = page.evaluate(
                    "bridge.requests.find(x=>x.method==='operations.start').params"
                )
                assert request["operation"] == "pymss.convert.batch", request
                assert request["inputs"]["files"]["paths"] == [
                    "/audio/source.wav",
                    "/audio/second.wav",
                ], request
                assert request["params"]["ogg_bit_rate"] == "450k", request
                expect(frame.locator(".audio-tool-status")).to_contain_text(
                    "source.ogg"
                )
                passed.append("batch-operation-progress-and-results")
                expect(frame.locator(".audio-tool-files > div")).to_have_count(0)
                expect(frame.locator(".audio-tool-actions button")).to_be_disabled()
                passed.append("successful-conversion-clears-inputs-and-keeps-results")
                page.wait_for_function("bridge.settings.form?.inputs?.length===0")
                settings_reads = page.evaluate(
                    "bridge.requests.filter(x=>x.method==='settings.read').length"
                )
                page.locator("#plugin").evaluate("frame=>{frame.src=frame.src}")
                page.wait_for_function(
                    "count=>bridge.requests.filter(x=>x.method==='settings.read').length>count",
                    arg=settings_reads,
                )
                expect(frame.locator(".audio-tool-files > div")).to_have_count(0)
                expect(frame.locator(".n-select").nth(0)).to_contain_text("OGG")
                passed.append("cleared-inputs-survive-component-remount")
                frame.get_by_role(
                    "button", name="Choose audio files", exact=True
                ).click()
                expect(frame.locator(".audio-tool-files > div")).to_have_count(2)
                page.evaluate("bridge.cancelNext=true")
                frame.locator(".audio-tool-actions button").click()
                frame.locator(".tool-log-button").click()
                frame.get_by_role("button", name="Cancel", exact=True).click()
                page.keyboard.press("Escape")
                page.wait_for_function(
                    "bridge.requests.some(x=>x.method==='operations.cancel')"
                )
                expect(frame.locator(".audio-tool-card--side")).to_contain_text("Cancelled")
                expect(frame.locator(".audio-tool-files > div")).to_have_count(2)
                passed.append("owned-cancellation-waits-for-terminal-response")
                page.evaluate("bridge.failNext=true")
                frame.locator(".audio-tool-actions button").click()
                expect(frame.locator(".audio-tool-card--side")).to_contain_text(
                    "Input audio is unavailable"
                )
                expect(frame.locator(".audio-tool-files > div")).to_have_count(2)
                passed.append("failure-clears-previous-results")
                page.locator("#plugin").evaluate("(frame)=>{frame.src=frame.src}")
                expect(frame.locator(".audio-tool-files > div")).to_have_count(2)
                expect(frame.locator(".n-select").nth(0)).to_contain_text("OGG")
                expect(frame.locator(".n-select").nth(3)).to_contain_text("450k")
                page.screenshot(
                    path=str(args.artifacts / "convert-light.png"), full_page=True
                )
                passed.append("settings-survive-component-remount")
            finally:
                page.close()
            page, frame = open_tool(browser, base, "convert", dark=True, width=420)
            try:
                expect(frame.locator(".audio-tool-card--main")).to_be_visible()
                assert page.frames[1].evaluate(
                    "document.documentElement.scrollWidth<=innerWidth"
                )
                page.screenshot(
                    path=str(args.artifacts / "convert-dark-narrow.png"), full_page=True
                )
                passed.append("narrow-dark-layout")
            finally:
                page.close()
        finally:
            browser.close()
    (args.artifacts / "results.json").write_text(
        json.dumps({"passed": passed}, indent=2), encoding="utf-8"
    )
    print(f"Component converter smoke passed: {len(passed)} checks")


if __name__ == "__main__":
    main()
