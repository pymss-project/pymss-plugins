"""Verify duration controls with both algorithms and streamed task progress."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from tool_views_smoke import ROOT, complete, fill_audio, open_tool, select, server_url


def file_result(path, legacy=False):
    return {"audio": {"kind": "opaque", "value": path} if legacy else
            {"kind": "file", "mediaType": "audio/wav", "path": path}}


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
                output_directory = tool.locator("#output-directory input")
                expect(output_directory).to_have_value("/output")
                choose_directory = tool.get_by_role("button", name="选择输出目录", exact=True)
                choose_directory.click()
                expect(output_directory).to_have_value("/output")
                selected_directory = "/output/处理结果 folder"
                page.evaluate("value=>bridge.directorySelection=value", selected_directory)
                choose_directory.click()
                expect(output_directory).to_have_value(selected_directory)
                expect(tool.locator("#param-algorithm")).to_contain_text("Rubber Band")
                duration = tool.locator("#param-duration_percent input")
                expect(tool.locator('label[for="param-duration_percent"]')).to_have_text("时长（%）")
                expect(duration).to_be_enabled()
                duration.fill("140")
                duration.press("Tab")
                tool.locator("#param-algorithm").click()
                expect(tool.locator(".n-base-select-option:visible")).to_have_count(3)
                page.screenshot(path=str(args.artifacts / f"algorithm-options-{width}.png"), full_page=True)
                tool.locator(".n-base-select-option").filter(has_text="Radius - radix2（上限最高，速度最慢）").click()
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
                assert request["params"]["outputDir"] == selected_directory, request
                expect(output_directory).to_be_disabled()
                expect(choose_directory).to_be_disabled()
                assert request["params"]["operation"] == "pymss.timing.process_file", request
                assert request["params"]["inputs"]["audio"] == "/audio/source.wav", request
                assert request["params"]["params"] == {"algorithm": "radius", "n_steps": 3, "duration_percent": 50}, request
                page.evaluate("""() => document.querySelector('#plugin').contentWindow.postMessage({
                    jsonrpc:'2.0',method:'task.progress',params:{
                        id:bridge.active.id,operation:bridge.active.params.operation,fraction:0.42,message:'Processing audio (Radius)'
                }},'*')""")
                tool.locator(".tool-log-button").click()
                expect(tool.locator("#progress")).to_be_visible()
                expect(tool.locator(".operation-detail").filter(has_text="42%")).to_be_visible()
                page.screenshot(path=str(args.artifacts / f"radius-progress-{width}.png"), full_page=True)
                complete(page, file_result(selected_directory + "/source_processed.wav", legacy=dark))
                expect(tool.locator("#run")).to_be_enabled()
                page.keyboard.press("Escape")
                expect(tool.locator("#results strong")).to_have_text("输出音频")
                tool.get_by_role("button", name="打开输出位置", exact=True).click()
                page.wait_for_function("value=>bridge.requests.some(item=>item.method==='files.reveal' && item.params.path===value)", arg=selected_directory + "/source_processed.wav")
                page.evaluate("bridge.active=null")
                select(tool, "#param-algorithm", "Radius - rustfft（上限更高，速度较慢）")
                expect(duration).to_have_value("50")
                tool.locator("#run").click()
                page.wait_for_function("bridge.active!==null")
                request = page.evaluate("bridge.active")
                assert request["params"]["params"] == {"algorithm": "radius_rustfft", "n_steps": 3, "duration_percent": 50}, request
                complete(page, file_result(selected_directory + "/source_rustfft.wav", legacy=dark))
                expect(tool.locator("#run")).to_be_enabled()
                expect(tool.locator("#param-algorithm")).to_contain_text("Radius - rustfft")
                expect(duration).to_have_value("50")
                page.evaluate("bridge.active=null")
                select(tool, "#param-algorithm", "Rubber Band（音质出色，速度更快）")
                expect(duration).to_be_enabled()
                expect(duration).to_have_value("50")
                duration.fill("200")
                duration.press("Tab")
                expect(tool.locator(".n-base-select-option:visible")).to_have_count(0)
                selected_directory += "_manual"
                output_directory.fill(selected_directory)
                output_directory.press("Tab")
                page.screenshot(path=str(args.artifacts / f"rubberband-editable-{width}.png"), full_page=True)
                tool.locator("#run").click()
                page.wait_for_function("bridge.active!==null")
                request = page.evaluate("bridge.active")
                assert request["params"]["outputDir"] == selected_directory, request
                assert request["params"]["params"] == {"algorithm": "rubberband", "n_steps": 3, "duration_percent": 200}, request
                complete(page, file_result(selected_directory + "/source_processed.wav", legacy=dark))
                expect(tool.locator("#run")).to_be_enabled()
                page.wait_for_function("value=>bridge.settings.form.outputDir===value", arg=selected_directory)
                ready_count = page.evaluate("bridge.requests.filter(item=>item.method==='pymss.ready').length")
                page.locator("#plugin").evaluate("frame=>{frame.src=frame.src}")
                page.wait_for_function("before=>bridge.requests.filter(item=>item.method==='pymss.ready').length>before", arg=ready_count)
                expect(output_directory).to_have_value(selected_directory)
                output_directory.fill("")
                tool.locator("#run").click()
                page.wait_for_function("bridge.active!==null && !Object.hasOwn(bridge.active.params,'outputDir')")
                complete(page, file_result("/output/source_processed.wav", legacy=dark))
                expect(tool.locator("#run")).to_be_enabled()
                select(tool, "#param-algorithm", "Radius - rustfft（上限更高，速度较慢）")
                tool.locator("#param-n_steps input").fill("3")
                tool.locator("#param-n_steps input").press("Tab")
                for locale in ["zh-CN", "en"]:
                    messages = json.loads((ROOT / f"plugins/timing/ui/src/locales/{locale}.json").read_text(encoding="utf-8"))
                    page.evaluate("locale=>document.querySelector('#plugin').contentWindow.postMessage({jsonrpc:'2.0',method:'host.theme',params:{locale}},'*')", locale)
                    expect(tool.locator("#run")).to_contain_text(messages["pluginTools"]["run"])
                    for code, key, data in [
                        ("TIMING_RADIUS_GLIBC_UNSUPPORTED", "radiusGlibcUnsupported", {"requiredGlibc": "2.43", "currentGlibc": "2.35"}),
                        ("TIMING_RADIUS_GLIBC_UNAVAILABLE", "radiusGlibcUnavailable", {"requiredGlibc": "2.43"}),
                        ("TIMING_RADIUS_RUNTIME_INVALID", "radiusRuntimeInvalid", {}),
                    ]:
                        page.evaluate("bridge.active=null")
                        tool.locator("#run").click()
                        page.wait_for_function("bridge.active!==null")
                        page.evaluate("""value=>document.querySelector('#plugin').contentWindow.postMessage({
                            jsonrpc:'2.0',id:bridge.active.id,error:{code:-32000,message:'Raw compatibility error',data:value}
                        },'*')""", {"code": code, **data})
                        expected = messages["plugin"]["errors"][key].format(required="2.43", current="2.35")
                        expect(tool.locator("#error")).to_have_text(expected)
                        expect(tool.locator("#run")).to_be_enabled()
                        expect(tool.locator("#results")).to_have_count(0)
                        if key == "radiusGlibcUnsupported":
                            page.screenshot(path=str(args.artifacts / f"glibc-error-{locale}-{width}.png"), full_page=True)
                page.close()
            print(json.dumps({"radiusBackends": ["radix2", "rustfft"], "radiusDuration": "50%, editable", "rubberbandDuration": "200%, editable", "progress": "42%", "themes": 2, "outputDirectory": "selected, restored and defaulted", "resultLabel": "localized", "compatibilityErrors": "3 codes, Chinese and English"}))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
