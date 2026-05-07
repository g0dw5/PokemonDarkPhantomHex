from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "editor"
sys.path.insert(0, str(EDITOR))

import pokemon_save_core as core  # noqa: E402
import web_save_editor as editor  # noqa: E402


def write_minimal_save(path: Path) -> None:
    data = bytearray(0x20000)
    for block_base, save_index in ((0, 2), (core.SAVE_BLOCK_SIZE, 1)):
        for section_id in range(14):
            section_start = block_base + section_id * core.SECTION_SIZE
            section = data[section_start : section_start + core.SECTION_SIZE]
            if section_id == 0:
                section[core.TRAINER_NAME_OFFSET : core.TRAINER_NAME_OFFSET + 7] = b"TEST\xff\xff\xff"
                section[core.TRAINER_GENDER_OFFSET] = 0
                _w16(section, core.TRAINER_ID_OFFSET, 1234)
                _w16(section, core.SECRET_ID_OFFSET, 5678)
            if section_id == 1:
                _w32(section, core.PARTY_COUNT_OFFSET, 0)
            _w16(section, 0x0FF4, section_id)
            _w32(section, 0x0FF8, core.SIGNATURE)
            _w32(section, 0x0FFC, save_index)
            _w16(section, 0x0FF6, core.EmeraldSave.section_checksum(section, section_id))
            data[section_start : section_start + core.SECTION_SIZE] = section
    path.write_bytes(data)


def _w16(buf: bytearray, offset: int, value: int) -> None:
    buf[offset : offset + 2] = int(value).to_bytes(2, "little")


def _w32(buf: bytearray, offset: int, value: int) -> None:
    buf[offset : offset + 4] = int(value).to_bytes(4, "little")


class WebEditorBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self) -> None:
        editor.api_close()
        self.server = editor.ThreadingHTTPServer((editor.HOST, editor.available_port(editor.HOST, 8810)), editor.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.url = f"http://{host}:{port}/"
        self.context = self.browser.new_context()
        self.page = self.context.new_page()

    def tearDown(self) -> None:
        self.context.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        editor.api_close()

    def test_unloaded_state_and_dictionary_layout(self) -> None:
        self.page.goto(self.url)

        expect(self.page.locator("#file-name")).to_have_text("未加载存档")
        expect(self.page.locator("#dirty-pill")).to_have_text("未加载")
        expect(self.page.locator("#rom-pill")).to_have_text("ROM 未加载")
        expect(self.page.locator("#reload-btn")).to_be_disabled()
        expect(self.page.locator("#save-btn")).to_be_disabled()
        expect(self.page.locator("#close-btn")).to_be_disabled()
        expect(self.page.locator("#content")).to_contain_text("请选择存档文件")

    def test_loaded_save_bag_edit_save_and_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_path = Path(tmp) / "sample.sav"
            write_minimal_save(save_path)
            editor.load_save(save_path)

            self.page.goto(self.url)
            expect(self.page.locator("#file-name")).to_have_text("sample.sav")
            expect(self.page.locator("#dirty-pill")).to_have_text("已保存")
            expect(self.page.locator("#rom-pill")).to_have_text("ROM 缺失")

            self.page.get_by_role("button", name="背包").click()
            expect(self.page.locator("#summary")).to_contain_text("背包：0 个非空格")
            self.page.locator("tbody tr").first.click()
            expect(self.page.locator("#inspector-title")).to_contain_text("电脑道具 #1")

            self.page.locator("#item_id").fill("13")
            self.page.locator("#quantity").fill("2")
            self.page.get_by_role("button", name="写入该格").click()
            expect(self.page.locator("#dirty-pill")).to_have_text("未保存")
            expect(self.page.locator("#save-btn")).to_be_enabled()
            expect(self.page.locator("#status")).to_contain_text("尚未保存到文件")

            self.page.get_by_role("button", name="保存").click()
            expect(self.page.locator("#dirty-pill")).to_have_text("已保存")
            expect(self.page.locator("#save-btn")).to_be_disabled()
            self.assertTrue(list(Path(tmp).glob("sample.bak-*.sav")))

            saved = core.EmeraldSave(save_path)
            item = next(entry for entry in saved.read_bag() if entry.pocket == "电脑道具" and entry.slot == 1)
            self.assertEqual((item.item_id, item.quantity), (13, 2))

            self.page.get_by_role("button", name="关闭").click()
            expect(self.page.locator("#file-name")).to_have_text("未加载存档")
            expect(self.page.locator("#content")).to_contain_text("请选择存档文件")

    def test_dictionary_tab_has_no_intro_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_path = Path(tmp) / "sample.sav"
            write_minimal_save(save_path)
            editor.load_save(save_path)

            self.page.goto(self.url)
            self.page.get_by_role("button", name="字典表").click()

            expect(self.page.locator(".dictionary-tabs")).to_be_visible()
            expect(self.page.locator(".dictionary-tabs input")).to_have_attribute("placeholder", "按 ID、字码、名称、说明搜索")
            expect(self.page.locator(".metric")).to_have_count(0)
            expect(self.page.locator("#inspector-title")).to_have_text("未选择字典项")


if __name__ == "__main__":
    unittest.main()
