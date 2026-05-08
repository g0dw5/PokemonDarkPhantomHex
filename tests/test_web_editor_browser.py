from __future__ import annotations

import sys
import re
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "editor"
sys.path.insert(0, str(EDITOR))

import pokemon_save_core as core  # noqa: E402
import web_save_editor as editor  # noqa: E402


def build_pokemon_raw(
    *,
    size: int,
    personality: int,
    ot_id: int,
    species: int,
    held_item: int = 0,
    experience: int = 0,
    friendship: int = 70,
    moves: tuple[int, int, int, int] = (33, 45, 0, 0),
    pps: tuple[int, int, int, int] = (35, 30, 0, 0),
    evs: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0),
    ivs: tuple[int, int, int, int, int, int] = (1, 2, 3, 4, 5, 6),
    ability_bit: int = 0,
    is_egg: bool = False,
    level: int = 12,
    met_location: int = 13,
    met_level: int = 5,
    caught_ball: int = 4,
) -> bytes:
    raw = bytearray(size)
    _w32(raw, 0, personality)
    _w32(raw, 4, ot_id)
    parts = {name: bytearray(12) for name in "GAEM"}
    _w16(parts["G"], 0, species)
    _w16(parts["G"], 2, held_item)
    _w32(parts["G"], 4, experience)
    parts["G"][9] = friendship
    for index, move_id in enumerate(moves):
        _w16(parts["A"], index * 2, move_id)
        parts["A"][8 + index] = pps[index]
    for index, value in enumerate(evs):
        parts["E"][index] = value
    iv_word = 0
    for index, value in enumerate(ivs):
        iv_word |= (value & 0x1F) << (index * 5)
    iv_word |= (1 if is_egg else 0) << 30
    iv_word |= (ability_bit & 1) << 31
    parts["M"][1] = met_location & 0xFF
    origin_word = (met_level & 0x7F) | ((caught_ball & 0xF) << 11)
    _w16(parts["M"], 2, origin_word)
    _w32(parts["M"], 4, iv_word)
    decrypted = core.join_substructures(personality, parts)
    _w16(raw, 0x1C, core.pokemon_checksum(decrypted))
    raw[0x20:0x50] = core.encrypt_substructures(raw, decrypted)
    if size >= core.PARTY_SIZE:
        raw[0x54] = level
        _w16(raw, 0x56, 30)
        _w16(raw, 0x58, 30)
        _w16(raw, 0x5A, 18)
        _w16(raw, 0x5C, 17)
        _w16(raw, 0x5E, 20)
        _w16(raw, 0x60, 16)
        _w16(raw, 0x62, 15)
    parsed = core.parse_pokemon(bytes(raw))
    assert parsed.checksum_stored == parsed.checksum_calculated
    return bytes(raw)


def write_save_fixture(path: Path) -> None:
    core.SPECIES_NAMES.update({25: "皮卡丘", 129: "鲤鱼王", 130: "暴鲤龙", 133: "伊布"})
    core.ITEM_NAMES.update({0: "空", 13: "伤药", 189: "神奇糖果"})
    core.MOVE_NAMES.update({33: "撞击", 45: "叫声", 150: "跃起"})
    data = bytearray(0x20000)
    party_raw = build_pokemon_raw(
        size=core.PARTY_SIZE,
        personality=0x12345678,
        ot_id=0x87654321,
        species=25,
        held_item=13,
        experience=1000,
        friendship=80,
        level=12,
    )
    box_raw = build_pokemon_raw(
        size=core.BOX_POKEMON_SIZE,
        personality=0x22223333,
        ot_id=0x87654321,
        species=129,
        held_item=0,
        experience=500,
        friendship=50,
        moves=(150, 0, 0, 0),
        pps=(15, 0, 0, 0),
    )
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
                _w32(section, core.PARTY_COUNT_OFFSET, 1)
                section[core.PARTY_OFFSET : core.PARTY_OFFSET + core.PARTY_SIZE] = party_raw
            if section_id == 5:
                section[core.BOX_DATA_OFFSET : core.BOX_DATA_OFFSET + core.BOX_POKEMON_SIZE] = box_raw
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
        expect.set_options(timeout=60000)
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

    def goto_loaded_save(self, save_path: Path) -> None:
        self.page.goto(f"{self.url}?save={quote(str(save_path))}")
        expect(self.page.locator("#file-name")).to_have_text(save_path.name)

    def test_unloaded_state_and_dictionary_layout(self) -> None:
        self.page.goto(self.url)

        expect(self.page.locator("#file-name")).to_have_text("未加载存档")
        expect(self.page.locator("#dirty-pill")).to_have_text("未加载")
        expect(self.page.locator("#rom-pill")).to_have_text("ROM 未加载")
        expect(self.page.locator("#reload-btn")).to_be_disabled()
        expect(self.page.locator("#save-btn")).to_be_disabled()
        expect(self.page.locator("#close-btn")).to_be_disabled()
        expect(self.page.locator("#content")).to_contain_text("请选择存档文件")

    def test_dictionary_tab_has_no_intro_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_path = Path(tmp) / "sample.sav"
            write_save_fixture(save_path)
            self.goto_loaded_save(save_path)

            self.page.get_by_role("button", name="字典表").click()

            expect(self.page.locator(".dictionary-tabs")).to_be_visible()
            expect(self.page.locator(".dictionary-tabs input")).to_have_attribute("placeholder", "按 ID、名称、说明搜索")
            expect(self.page.locator(".dictionary-tabs")).not_to_contain_text("全部")
            self.assertEqual(self.page.locator(".dictionary-tabs").evaluate("node => getComputedStyle(node).position"), "sticky")
            expect(self.page.locator(".metric")).to_have_count(0)
            expect(self.page.locator("#inspector-title")).to_have_text("未选择字典项")

            for tab_name in ("宝可梦", "地图", "特性", "招式", "道具"):
                self.page.locator(".dictionary-tabs").get_by_role("button", name=tab_name).click()
                expect(self.page.locator(".dictionary-table thead")).not_to_contain_text("字码")
                expect(self.page.locator(".dictionary-table thead")).not_to_contain_text("描述来源")

            self.page.evaluate("""() => {
                const species = {table: "species", table_label: "宝可梦", id: 25, name: "皮卡丘", decoded: "皮卡丘", detail: {types: ["电", "飞行"], base_stats: {hp: 35, attack: 55, defense: 40, speed: 90, sp_attack: 50, sp_defense: 50}, growth_rate: "中速", gender_ratio: "雌雄各半", encounters: [{map_group: 0, map_number: 18, location: "103号道路", method: "草丛", min_level: 3, max_level: 6, rate: 20}]}};
                const bulbasaur = {table: "species", table_label: "宝可梦", id: 1, name: "妙蛙种子", decoded: "妙蛙种子", detail: {types: ["草"], encounters: [{map_group: 0, map_number: 20, location: "105号水路", method: "草丛", min_level: 7, max_level: 7, rate: 20, encounter_rate: 15}]}};
                const raikou = {table: "species", table_label: "宝可梦", id: 243, name: "雷公", decoded: "雷公", detail: {types: ["电"], encounters: [{map_group: 34, map_number: 12, location: "冥想之窟", method: "定点", min_level: 40, max_level: 40, source_type: "static"}]}};
                const map103 = {table: "maps", table_label: "地图", id: "0-18", sort_id: 18, name: "103号道路", decoded: "103号道路", detail: {map_group: 0, map_number: 18, map_key: "Route103", region_map_section_id: 18, layout: {width: 80, height: 22}, connections: [{direction_name: "右", map_id: "0-19", name: "104号道路"}], encounters: [{species_id: 25, species_name: "皮卡丘", method: "草丛", min_level: 3, max_level: 6, rate: 20}, {species_id: 129, species_name: "鲤鱼王", method: "旧钓竿", min_level: 5, max_level: 5, rate: 70}, {species_id: 183, species_name: "玛力露", method: "冲浪", min_level: 20, max_level: 25, rate: 60}]}};
                const map104 = {table: "maps", table_label: "地图", id: "0-19", sort_id: 19, name: "104号道路", decoded: "104号道路", detail: {map_group: 0, map_number: 19, map_key: "Route104", region_map_section_id: 19, layout: {width: 90, height: 30}, connections: [{direction_name: "左", map_id: "0-18", name: "103号道路"}], encounters: []}};
                names = {ok: true, rows: [species, bulbasaur, raikou, map103, map104], species: [species, bulbasaur, raikou], maps: [map103, map104], items: [], moves: [], abilities: [], stats: {rom: {}, charmap: {}}, table_info: {}};
                tab = "names";
                collectTable = "species";
                render();
            }""")
            expect(self.page.locator(".dictionary-species tbody tr").first.locator(".types-cell .type-badge")).to_have_count(2)
            self.assertEqual(self.page.locator(".dictionary-species tbody tr").first.locator(".types-cell .pokemon-type-row").evaluate("node => getComputedStyle(node).flexWrap"), "nowrap")
            expect(self.page.locator(".dictionary-species thead")).to_contain_text("经验曲线")
            expect(self.page.locator(".dictionary-species thead")).to_contain_text("性别")
            expect(self.page.locator(".dictionary-species thead")).not_to_contain_text("成长")
            expect(self.page.locator(".dictionary-species .base-stat")).to_have_count(6)
            expect(self.page.locator(".dictionary-species .base-stat-value").first).to_have_text("35")
            expect(self.page.locator(".dictionary-species")).to_contain_text("妙蛙种子")
            expect(self.page.locator(".dictionary-species")).to_contain_text("105号水路 草丛 Lv7 20%")
            expect(self.page.locator(".dictionary-species")).to_contain_text("冥想之窟 定点 Lv40")
            self.page.locator(".dictionary-species tbody tr").first.click()
            expect(self.page.locator("#detail .type-badge")).to_have_count(2)
            self.page.locator("#detail").get_by_role("button", name=re.compile("103号道路 草丛")).click()
            expect(self.page.locator("#inspector-title")).to_contain_text("地图 #0-18")
            expect(self.page.locator(".dictionary-maps")).to_be_visible()
            expect(self.page.locator(".dictionary-maps thead")).not_to_contain_text("Connections")
            expect(self.page.locator(".dictionary-maps thead")).to_contain_text("Encounters")
            expect(self.page.locator(".dictionary-maps .encounter-group-label")).to_contain_text(["草丛", "钓鱼", "冲浪"])
            expect(self.page.locator("#detail")).not_to_contain_text("Connections")
            expect(self.page.locator("#detail")).not_to_contain_text("右 104号道路")
            expect(self.page.locator("#detail .encounter-group-label")).to_contain_text(["草丛", "钓鱼", "冲浪"])
            self.page.locator("#detail").get_by_role("button", name=re.compile("皮卡丘 草丛")).click()
            expect(self.page.locator("#inspector-title")).to_contain_text("宝可梦 #25")

            self.page.evaluate("""() => {
                const row = {table: "items", table_label: "道具", id: 13, name: "伤药", decoded: "伤药", tokens: ["03"], locations: ["电脑道具 #1 x8"], detail: {price: 300, pocket: "道具"}};
                names = {ok: true, rows: [row], items: [row], species: [], maps: [], moves: [], abilities: [], stats: {rom: {}, charmap: {}}, table_info: {}};
                tab = "names";
                collectTable = "items";
                collectSearch = "";
                render();
            }""")
            self.page.get_by_role("button", name="电脑道具 #1 x8").click()
            expect(self.page.locator("#tab-bag")).to_have_class(re.compile("active"))
            expect(self.page.locator("#inspector-title")).to_have_text("电脑道具 #1")
            expect(self.page.locator("#item_id")).to_be_visible()

            self.page.get_by_role("button", name="字典表").click()
            self.page.get_by_role("button", name="属性克制").click()
            expect(self.page.locator(".type-chart")).to_be_visible()
            expect(self.page.locator("#inspector-title")).to_have_text("属性克制表")
            expect(self.page.locator(".dictionary-tabs")).to_contain_text("17 属性")
            expect(self.page.locator(".type-chart")).not_to_contain_text("未知09")
            expect(self.page.locator(".type-profile")).to_contain_text("4 倍弱点")
            expect(self.page.locator(".type-profile")).to_contain_text("电")
            expect(self.page.locator(".type-profile")).to_contain_text("草")
            expect(self.page.locator(".type-chart tbody tr").filter(has_text="电").locator("td").nth(10)).to_have_text("2x")

    def test_bag_edit_save_reload_and_close_from_loaded_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_path = Path(tmp) / "sample.sav"
            write_save_fixture(save_path)
            self.goto_loaded_save(save_path)

            expect(self.page.locator("#dirty-pill")).to_have_text("已保存")
            expect(self.page.locator("#rom-pill")).to_have_text("ROM 缺失")
            self.page.get_by_role("button", name="背包").click()
            expect(self.page.locator("#summary")).to_contain_text("背包：0 个非空格")
            self.page.locator("#content tbody tr").first.click()
            expect(self.page.locator("#inspector-title")).to_contain_text("电脑道具 #1")
            expect(self.page.locator("#item_id")).to_be_visible()

            for quantity in (2, 5, 9):
                self.page.locator("#content tbody tr").first.click()
                expect(self.page.locator("#item_id")).to_be_visible()
                self.page.locator("#item_id").fill("13")
                self.page.locator("#quantity").fill(str(quantity))
                self.page.locator("#form button.primary").evaluate("button => button.click()")
                expect(self.page.locator("#dirty-pill")).to_have_text(re.compile(r"未保存 \d+"))
                self.page.locator("#dirty-pill").click()
                expect(self.page.locator("#inspector-title")).to_have_text("未保存修改")
                expect(self.page.locator("#detail")).to_contain_text("已写入背包")
                expect(self.page.locator("#detail")).to_contain_text("道具")
                expect(self.page.locator("#detail")).to_contain_text("数量")
                expect(self.page.locator("#status")).to_contain_text("尚未保存到文件")
                self.page.get_by_role("button", name="保存").click()
                expect(self.page.locator("#dirty-pill")).to_have_text("已保存")
                self.page.get_by_role("button", name="重载").click()
                self.assert_bag_entry(save_path, 13, quantity)

            self.assertGreaterEqual(len(list(Path(tmp).glob("sample.bak-*.sav"))), 3)
            self.page.get_by_role("button", name="关闭").click()
            expect(self.page.locator("#file-name")).to_have_text("未加载存档")
            expect(self.page.locator("#content")).to_contain_text("请选择存档文件")

    def test_pokemon_form_control_matrix_and_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_path = Path(tmp) / "sample.sav"
            write_save_fixture(save_path)
            self.goto_loaded_save(save_path)
            self.page.evaluate("""() => {
                const species = {table: "species", table_label: "宝可梦", id: 25, name: "皮卡丘", decoded: "皮卡丘", tokens: ["01"], detail: {types: ["电"], encounters: [{location: "103号道路", method: "草丛", min_level: 3, max_level: 6, rate: 20, slots: [1, 2]}]}};
                names = {...names, rows: [species], species: [species]};
                renderDatalists();
            }""")
            self.page.locator("#tab-pokemon").click()
            self.page.locator(".party-grid .box-slot.occupied").first.click()
            expect(self.page.locator(".party-storage")).to_have_class(re.compile("active"))
            expect(self.page.locator(".party-grid .box-slot.occupied.selected")).to_have_count(1)
            expect(self.page.locator(".pokemon-table tbody tr.selected")).to_have_count(1)
            expect(self.page.locator("#inspector-title")).to_contain_text("皮卡丘")
            expect(self.page.locator("#detail")).not_to_contain_text("合法性通过")
            expect(self.page.locator("#form")).to_contain_text("写入宝可梦")
            expect(self.page.locator("#form-types")).to_contain_text("电")
            expect(self.page.locator("#form-encounters")).to_contain_text("地点 #13")
            expect(self.page.locator("#form-encounters")).to_contain_text("初始 Lv5")
            expect(self.page.locator("#form-encounters")).not_to_contain_text("几率 20%")
            expect(self.page.locator("#form-encounters")).not_to_contain_text("槽位")
            self.assertLess(
                self.page.locator("#move-controls").evaluate("node => [...node.parentElement.children].indexOf(node)"),
                self.page.locator("#form-encounters").evaluate("node => [...node.parentElement.children].indexOf(node)"),
            )

            case_count = 0
            case_count += self.assert_input_cases("#species", ["#25 · 皮卡丘", "#133 · 伊布", "#129 · 鲤鱼王", "#25 · 皮卡丘"])
            case_count += self.assert_input_cases("#held_item", ["#13 · 伤药", "#189 · 神奇糖果", "#0 · 空", "#13 · 伤药"])
            case_count += self.assert_input_cases("#level", [str(value) for value in (1, 5, 12, 33, 50, 66, 75, 88, 99, 100, 12)])
            case_count += self.assert_input_cases("#friendship", [str(value) for value in (0, 1, 10, 70, 100, 150, 200, 220, 250, 255, 80)])
            case_count += self.assert_input_cases("#ivs", [
                "0,0,0,0,0,0",
                "31,31,31,31,31,31",
                "1,2,3,4,5,6",
                "6,5,4,3,2,1",
                "10,11,12,13,14,15",
                "20,21,22,23,24,25",
                "30,29,28,27,26,25",
                "7,8,9,10,11,12",
                "13,14,15,16,17,18",
                "1,2,3,4,5,6",
            ])
            case_count += self.assert_input_cases("#evs", [
                "0,0,0,0,0,0",
                "85,85,85,85,85,85",
                "252,0,0,252,6,0",
                "0,252,0,6,252,0",
                "100,100,100,100,100,10",
                "1,2,3,4,5,6",
                "10,20,30,40,50,60",
                "60,50,40,30,20,10",
                "0,0,255,0,255,0",
                "1,2,3,4,5,6",
            ])
            case_count += self.assert_select_cases("#nature_id", [str(value) for value in range(25)] + ["3"])
            case_count += self.assert_select_cases("#caught_ball", [str(value) for value in range(16)] + ["4"])
            case_count += self.assert_select_cases("#gender", ["雄", "雌", "无性别", "雄"])
            case_count += self.assert_select_cases("#move_0", ["33", "45", "0", "33"])
            case_count += self.assert_select_cases("#move_1", ["45", "33", "0", "45"])
            case_count += self.assert_select_cases("#move_2", ["0"])
            case_count += self.assert_select_cases("#move_3", ["0"])
            for slot in range(4):
                for value in range(4):
                    with self.subTest(control=f"pp_up_{slot}", value=value):
                        self.page.locator(f"#pp_up_{slot} + .pp-up-control button").nth(value).click()
                        self.assertEqual(self.page.locator(f"#pp_up_{slot}").input_value(), str(value))
                        case_count += 1
            for toggle in ("is_egg", "is_shiny", "is_egg", "is_shiny", "is_egg", "is_shiny"):
                with self.subTest(control=toggle):
                    current = self.page.locator(f"#{toggle}").input_value()
                    self.page.locator(f"#{toggle} + .single-toggle").click()
                    self.assertNotEqual(self.page.locator(f"#{toggle}").input_value(), current)
                    case_count += 1

            self.assertGreaterEqual(case_count, 100)

            self.page.locator("#tab-pokemon").click()
            self.page.locator("#content tbody tr").first.click()
            expect(self.page.locator(".party-storage")).to_have_class(re.compile("active"))
            expect(self.page.locator(".party-grid .box-slot.occupied.selected")).to_have_count(1)
            expect(self.page.locator(".pokemon-table tbody tr.selected")).to_have_count(1)
            expect(self.page.locator("#form")).to_contain_text("写入宝可梦")
            expect(self.page.locator("#form-encounters")).to_contain_text("地点 #13")
            expect(self.page.locator("#form-encounters")).to_contain_text("初始 Lv5")
            self.page.locator("#held_item").fill("#189 · 神奇糖果")
            self.page.locator("#level").fill("50")
            self.page.locator("#friendship").fill("220")
            self.page.locator("#ivs").fill("31,30,29,28,27,26")
            self.page.locator("#evs").fill("252,0,0,252,6,0")
            self.page.locator("#nature_id").select_option("3")
            self.page.locator("#gender").select_option("无性别")
            self.page.locator("#caught_ball").select_option("4")
            self.page.locator("#move_0").select_option("0")
            self.page.locator("#move_1").select_option("0")
            self.page.locator("#move_2").select_option("0")
            self.page.locator("#move_3").select_option("0")
            self.page.locator("#form button.primary").evaluate("button => button.click()")
            expect(self.page.locator("#dirty-pill")).to_have_text(re.compile(r"未保存 \d+"))
            self.page.get_by_role("button", name="保存").click()
            expect(self.page.locator("#dirty-pill")).to_have_text("已保存")
            self.page.get_by_role("button", name="重载").click()

            saved = core.EmeraldSave(save_path)
            party = saved.party()[0]
            self.assertEqual(party.species, 25)
            self.assertEqual(party.held_item, 189)
            self.assertEqual(party.level, 50)
            self.assertEqual(party.friendship, 220)
            self.assertEqual(party.ivs, [31, 30, 29, 28, 27, 26])
            self.assertEqual(party.evs, [252, 0, 0, 252, 6, 0])
            self.assertEqual(party.moves, [0, 0, 0, 0])
            self.assertEqual(party.checksum_stored, party.checksum_calculated)

    def test_box_pokemon_edit_save_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_path = Path(tmp) / "sample.sav"
            write_save_fixture(save_path)
            self.goto_loaded_save(save_path)

            self.page.locator("#tab-pokemon").click()
            expect(self.page.locator("#summary")).to_contain_text("宝可梦：队伍 1/6，盒子 1/420")
            expect(self.page.locator(".storage-card")).to_have_count(15)
            expect(self.page.locator(".party-storage")).to_have_count(1)
            expect(self.page.locator(".party-grid .party-slot")).to_have_count(6)
            self.assertEqual(self.page.locator(".party-grid").evaluate("node => getComputedStyle(node).gridTemplateColumns.split(' ').length"), 1)
            self.assertEqual(self.page.locator(".pokemon-layout").evaluate("node => getComputedStyle(node).overflow"), "hidden")
            self.assertEqual(self.page.locator(".pokemon-list").evaluate("node => getComputedStyle(node).overflowY"), "auto")
            self.assertEqual(self.page.locator(".pokemon-map").evaluate("node => getComputedStyle(node).overflowY"), "auto")
            expect(self.page.locator(".party-grid .box-slot.occupied").first).to_have_attribute("data-name", "皮卡丘")
            expect(self.page.locator(".storage-card:not(.party-storage) .box-slot.occupied").first).to_have_attribute("data-name", "鲤鱼王")
            expect(self.page.locator(".storage-card:not(.party-storage) .box-slot.occupied").first).to_have_attribute("title", "鲤鱼王")
            expect(self.page.locator("#content .subtabs")).to_have_count(0)
            self.page.locator(".storage-card:not(.party-storage) .box-slot.occupied").first.click()
            expect(self.page.locator("#summary")).to_contain_text("列表区：1号盒 1/30")
            expect(self.page.locator(".storage-card:not(.party-storage).active")).to_have_count(1)
            expect(self.page.locator(".storage-card:not(.party-storage) .box-slot.occupied.selected")).to_have_count(1)
            expect(self.page.locator(".pokemon-table tbody tr.selected")).to_have_count(1)
            expect(self.page.locator(".box-grid.active")).to_have_count(0)
            expect(self.page.locator(".pokemon-table tbody tr")).to_have_count(1)
            expect(self.page.locator("#inspector-title")).to_contain_text("鲤鱼王")
            expect(self.page.locator("#detail")).not_to_contain_text("合法性通过")
            self.page.locator(".pokemon-table tbody tr").first.click()
            expect(self.page.locator(".storage-card:not(.party-storage).active")).to_have_count(1)
            expect(self.page.locator(".storage-card:not(.party-storage) .box-slot.occupied.selected")).to_have_count(1)
            expect(self.page.locator(".pokemon-table tbody tr.selected")).to_have_count(1)
            self.page.locator(".storage-card:not(.party-storage).active .box-slot:not(.occupied)").first.click()
            expect(self.page.locator("#inspector-title")).to_have_text("未选择宝可梦")
            expect(self.page.locator("#form")).not_to_contain_text("写入宝可梦")
            expect(self.page.locator(".storage-card:not(.party-storage) .box-slot.occupied.selected")).to_have_count(0)
            expect(self.page.locator(".pokemon-table tbody tr.selected")).to_have_count(0)
            self.page.locator(".storage-card:not(.party-storage) .box-slot.occupied").first.click()
            expect(self.page.locator("#inspector-title")).to_contain_text("鲤鱼王")
            expect(self.page.locator("#form")).to_contain_text("写入宝可梦")
            self.page.locator("#species").fill("#130 · 暴鲤龙")
            self.page.locator("#held_item").fill("#189 · 神奇糖果")
            self.page.locator("#friendship").fill("100")
            self.page.locator("#nature_id").select_option("4")
            self.page.locator("#gender").select_option("无性别")
            self.page.get_by_role("button", name="写入宝可梦").click()
            expect(self.page.locator("#dirty-pill")).to_have_text(re.compile(r"未保存 \d+"))
            self.page.get_by_role("button", name="保存").click()
            self.page.get_by_role("button", name="重载").click()

            saved = core.EmeraldSave(save_path)
            box = saved.boxes()[0]
            self.assertEqual(box.species, 130)
            self.assertEqual(box.held_item, 189)
            self.assertEqual(box.friendship, 100)
            self.assertEqual((box.box, box.box_slot), (1, 1))
            self.assertEqual(box.checksum_stored, box.checksum_calculated)

    def assert_input_cases(self, selector: str, values: list[str]) -> int:
        count = 0
        for value in values:
            with self.subTest(control=selector, value=value):
                self.page.locator(selector).fill(value)
                self.assertEqual(self.page.locator(selector).input_value(), value)
                count += 1
        return count

    def assert_select_cases(self, selector: str, values: list[str]) -> int:
        count = 0
        for value in values:
            with self.subTest(control=selector, value=value):
                self.page.locator(selector).select_option(value)
                self.assertEqual(self.page.locator(selector).input_value(), value)
                count += 1
        return count

    def assert_bag_entry(self, save_path: Path, item_id: int, quantity: int) -> None:
        saved = core.EmeraldSave(save_path)
        item = next(entry for entry in saved.read_bag() if entry.pocket == "电脑道具" and entry.slot == 1)
        self.assertEqual((item.item_id, item.quantity), (item_id, quantity))


if __name__ == "__main__":
    unittest.main()
