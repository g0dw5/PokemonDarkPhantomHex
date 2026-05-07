from __future__ import annotations

import sys
import tempfile
import http.client
import json
import subprocess
import threading
import unittest
from pathlib import Path
from urllib.parse import quote
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "editor"
sys.path.insert(0, str(EDITOR))

import pokemon_save_core as core  # noqa: E402
import rom_data  # noqa: E402
import web_save_editor as editor  # noqa: E402
from test_web_editor_browser import build_pokemon_raw, write_save_fixture, _w16, _w32  # noqa: E402


def fake_rom(path: Path) -> None:
    rom_size = max(
        core.MOVE_DATA_OFFSET + core.ROM_MOVE_COUNT * core.MOVE_DATA_SIZE,
        core.TMHM_MOVES_OFFSET + core.TMHM_COUNT * 2,
        core.TUTOR_COMPATIBILITY_OFFSET + core.ROM_SPECIES_COUNT * core.TUTOR_COMPATIBILITY_SIZE,
    ) + 0x1000
    rom = bytearray(rom_size)
    species = 25
    stats = bytearray(28)
    stats[6] = 13
    stats[7] = 13
    stats[16] = 127
    stats[19] = 0
    stats[22] = 1
    stats[23] = 2
    start = core.BASE_STATS_OFFSET + species * core.BASE_STATS_SIZE
    rom[start : start + core.BASE_STATS_SIZE] = stats
    stats2 = bytearray(stats)
    stats2[22] = 3
    stats2[23] = 0
    start2 = core.BASE_STATS_OFFSET + 26 * core.BASE_STATS_SIZE
    rom[start2 : start2 + core.BASE_STATS_SIZE] = stats2

    for move_id, pp in ((33, 35), (45, 30), (150, 15), (151, 10)):
        rom[core.MOVE_DATA_OFFSET + move_id * core.MOVE_DATA_SIZE + core.MOVE_PP_OFFSET] = pp

    learnset_offset = 0x610000
    pointer_offset = core.LEVEL_UP_LEARNSET_POINTERS_OFFSET + (species + core.LEVEL_UP_LEARNSET_SPECIES_OFFSET) * 4
    _w32(rom, pointer_offset, core.GBA_ROM_POINTER_BASE + learnset_offset)
    _w16(rom, learnset_offset, (5 << 9) | 33)
    _w16(rom, learnset_offset + 2, (20 << 9) | 45)
    _w16(rom, learnset_offset + 4, 0xFFFF)

    evolution_offset = core.EVOLUTIONS_OFFSET + species * core.EVOLUTION_RECORD_SIZE
    _w16(rom, evolution_offset, 4)
    _w16(rom, evolution_offset + 2, 16)
    _w16(rom, evolution_offset + 4, 26)

    _w16(rom, core.EGG_MOVES_OFFSET, core.EGG_MOVE_SPECIES_MARKER_BASE + species)
    _w16(rom, core.EGG_MOVES_OFFSET + 2, 45)
    _w16(rom, core.EGG_MOVES_OFFSET + 4, 0xFFFF)

    for index, move_id in enumerate((33, 45, 150, 151)):
        _w16(rom, core.TMHM_MOVES_OFFSET + index * 2, move_id)
    rom[core.TMHM_COMPATIBILITY_OFFSET + species * core.TMHM_COMPATIBILITY_SIZE] = 0b00000011

    _w16(rom, core.TUTOR_MOVES_OFFSET, 150)
    _w16(rom, core.TUTOR_MOVES_OFFSET + 2, 151)
    _w16(rom, core.TUTOR_MOVES_OFFSET + 4, 0)
    rom[core.TUTOR_COMPATIBILITY_OFFSET + species * core.TUTOR_COMPATIBILITY_SIZE] = 0b00000001

    sprite_offset = 0x611000
    palette_offset = 0x612000
    sprite_payload = lz77_literal(bytes([0] * 2048))
    palette_payload = lz77_literal(bytes(range(32)))
    rom[sprite_offset : sprite_offset + len(sprite_payload)] = sprite_payload
    rom[palette_offset : palette_offset + len(palette_payload)] = palette_payload
    for table in (editor.FRONT_SPRITE_TABLE_OFFSET,):
        _w32(rom, table + species * editor.SPRITE_TABLE_ENTRY_SIZE, core.GBA_ROM_POINTER_BASE + sprite_offset)
    for table in (editor.NORMAL_PALETTE_TABLE_OFFSET, editor.SHINY_PALETTE_TABLE_OFFSET):
        _w32(rom, table + species * editor.SPRITE_TABLE_ENTRY_SIZE, core.GBA_ROM_POINTER_BASE + palette_offset)

    ability_desc_offset = 0x614000
    _w32(rom, rom_data.ABILITY_DESCRIPTION_EXT_POINTERS_OFFSET, core.GBA_ROM_POINTER_BASE + ability_desc_offset)
    rom[ability_desc_offset : ability_desc_offset + 4] = bytes([0xBB, 0xBC, 0xBD, 0xFF])

    wild_header = rom_data.WILD_ENCOUNTER_HEADERS_OFFSET
    wild_info = 0x613000
    wild_list = 0x613100
    rom[wild_header] = 1
    rom[wild_header + 1] = 2
    _w32(rom, wild_header + 4, core.GBA_ROM_POINTER_BASE + wild_info)
    rom[wild_header + rom_data.WILD_ENCOUNTER_HEADER_SIZE] = 0xFF
    rom[wild_header + rom_data.WILD_ENCOUNTER_HEADER_SIZE + 1] = 0xFF
    _w32(rom, wild_info, 20)
    _w32(rom, wild_info + 4, core.GBA_ROM_POINTER_BASE + wild_list)
    for slot in range(12):
        entry = wild_list + slot * 4
        rom[entry] = 3 + slot
        rom[entry + 1] = 5 + slot
        _w16(rom, entry + 2, species if slot < 2 else 26)
    path.write_bytes(rom)


def lz77_literal(payload: bytes) -> bytes:
    out = bytearray([0x10, len(payload) & 0xFF, (len(payload) >> 8) & 0xFF, (len(payload) >> 16) & 0xFF])
    for offset in range(0, len(payload), 8):
        chunk = payload[offset : offset + 8]
        out.append(0)
        out.extend(chunk)
    return bytes(out)


class BackendEditorTest(unittest.TestCase):
    def tearDown(self) -> None:
        editor.api_close()
        core.set_rom_path(None)

    def test_save_fixture_core_read_update_save_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_path = Path(tmp) / "sample.sav"
            write_save_fixture(save_path)
            save = core.EmeraldSave(save_path)
            self.assertEqual(save.party_count(), 1)
            self.assertEqual(save.party()[0].species, 25)
            self.assertEqual((save.boxes()[0].species, save.boxes()[0].box_slot), (129, 1))
            self.assertTrue(any(row["ok"] for row in save.section_summary()))
            self.assertIsInstance(save.validate(), list)

            save.write_bag_entry(core.BagEntry("普通道具", 1, 13, 3))
            item = next(entry for entry in save.read_bag() if entry.pocket == "普通道具" and entry.slot == 1)
            self.assertEqual((item.item_id, item.quantity), (13, 3))
            party = save.update_party_pokemon(1, {
                "species": 133,
                "held_item": 189,
                "friendship": 200,
                "moves": [33, 45, 0, 0],
                "pps": [35, 30, 0, 0],
                "evs": [1, 2, 3, 4, 5, 6],
                "ivs": [31, 30, 29, 28, 27, 26],
                "ability_bit": 0,
                "is_egg": False,
                "nature_id": 3,
                "gender": "无性别",
                "is_shiny": False,
                "caught_ball": 4,
                "level": 50,
            })
            self.assertEqual((party.species, party.level, party.friendship), (133, 50, 200))
            box = save.update_box_pokemon(1, 1, {
                "species": 130,
                "held_item": 189,
                "friendship": 100,
                "moves": [150, 0, 0, 0],
                "pps": [15, 0, 0, 0],
                "evs": [0, 0, 0, 0, 0, 0],
                "ivs": [1, 1, 1, 1, 1, 1],
                "ability_bit": 0,
                "is_egg": False,
                "nature_id": 4,
                "gender": "无性别",
                "is_shiny": False,
                "caught_ball": 4,
            })
            self.assertEqual((box.species, box.held_item), (130, 189))
            backup = save.save()
            self.assertTrue(backup.exists())
            reloaded = core.EmeraldSave(save_path)
            self.assertEqual(reloaded.party()[0].species, 133)
            self.assertEqual(reloaded.boxes()[0].species, 130)
            with self.assertRaises(ValueError):
                save.update_party_pokemon(9, {})
            with self.assertRaises(ValueError):
                save.update_box_pokemon(15, 1, {})
            with self.assertRaises(ValueError):
                save.write_bag_entry(core.BagEntry("普通道具", 999, 1, 1))

    def test_api_state_update_save_close_and_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_path = Path(tmp) / "sample.sav"
            write_save_fixture(save_path)
            editor.load_save(save_path)
            state = editor.api_state()
            self.assertTrue(state["ok"])
            self.assertEqual(state["party"][0]["species"], 25)
            self.assertTrue(editor.api_names()["ok"])
            self.assertTrue(editor.observed_from_save()["species"])

            bag = editor.api_update_bag({"pocket": "电脑道具", "slot": 1, "item_id": 13, "quantity": 8})
            self.assertIn("已写入背包", bag["message"])
            bag_change = editor.api_state()["changes"][0]
            self.assertIn("已写入背包", bag_change["summary"])
            self.assertTrue(any(diff["field"] == "道具" for diff in bag_change["diffs"]))
            party = editor.api_update_pokemon({
                "location": "party",
                "slot": 1,
                "species": "#25",
                "held_item": "#13",
                "friendship": 81,
                "nature_id": 1,
                "gender": "无性别",
                "is_shiny": 0,
                "caught_ball": 4,
                "moves": [33, 45, 0, 0],
                "pps": [35, 30, 0, 0],
                "evs": [0, 0, 0, 0, 0, 0],
                "ivs": [1, 2, 3, 4, 5, 6],
                "ability_bit": 0,
                "is_egg": 0,
                "level": 13,
            })
            self.assertIn("已写入队伍", party["message"])
            box = editor.api_update_pokemon({
                "location": "box",
                "box": 1,
                "box_slot": 1,
                "species": "#129",
                "held_item": "#0",
                "friendship": 50,
                "nature_id": 2,
                "gender": "无性别",
                "is_shiny": 0,
                "caught_ball": 4,
                "moves": [150, 0, 0, 0],
                "pps": [15, 0, 0, 0],
                "evs": [0, 0, 0, 0, 0, 0],
                "ivs": [1, 1, 1, 1, 1, 1],
                "ability_bit": 0,
                "is_egg": 0,
            })
            self.assertIn("已写入盒子", box["message"])
            self.assertEqual(len(editor.api_state()["changes"]), 3)
            self.assertTrue(editor.api_save()["ok"])
            self.assertEqual(editor.api_state()["changes"], [])
            closed = editor.api_close()
            self.assertFalse(closed["ok"])
            with self.assertRaises(ValueError):
                editor.require_save()
            editor.load_save(Path(tmp) / "missing.sav")
            self.assertFalse(editor.api_state()["ok"])
            self.assertEqual(editor.parse_list("1,2,3", 3), [1, 2, 3])
            with self.assertRaises(ValueError):
                editor.parse_list("1,2", 3)
            self.assertEqual(editor.parse_id("#25 · 皮卡丘"), 25)

    def test_rom_constraints_personality_experience_and_sprite_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rom_path = Path(tmp) / "sample.gba"
            fake_rom(rom_path)
            core.set_rom_path(rom_path)
            editor.configure_rom(rom_path)

            constraints = core.constraints_for_species(25)
            self.assertIsNotNone(constraints)
            self.assertEqual(core.default_pp_for_move(33), 35)
            self.assertEqual(core.tmhm_move_for_item(core.TMHM_FIRST_ITEM_ID), 33)
            self.assertIn(26, core._previous_species_by_target())
            self.assertIn("雄", core.gender_options_for_species(25))
            self.assertEqual(core.species_type_names(25), ["电"])
            self.assertEqual(core.ability_options_for_species(25), [(0, 1), (1, 2)])
            legality = core.move_legality_for_species(25, 10, 33)
            self.assertTrue(legality.is_known_legal)
            api_constraints = editor.api_pokemon_constraints(25, 10)
            self.assertTrue(api_constraints["available"])
            self.assertTrue(api_constraints["moves"])
            rom_text = rom_data.extract_rom_text(rom_path)
            self.assertEqual(rom_text["abilities"]["78"]["description"], "ABC")
            encounters = rom_text["species"]["25"]["detail"]["encounters"]
            self.assertEqual(encounters[0]["location"], "地图 1-2")
            self.assertEqual(encounters[0]["method"], "草丛")
            self.assertEqual((encounters[0]["min_level"], encounters[0]["max_level"]), (3, 6))

            for growth_rate in range(6):
                self.assertGreaterEqual(core.experience_for_level(growth_rate, 20), 0)
            self.assertEqual(core.level_for_experience(25, core.experience_for_level(0, 20)), 20)
            personality = 0x12345678
            preview = editor.api_personality_preview(25, personality, 0x87654321)
            adjusted = editor.api_personality_adjust(25, personality, 0x87654321, preview["nature_id"], preview["gender"], preview["is_shiny"])
            self.assertEqual(adjusted["personality"], personality)

            self.assertFalse(editor.api_pokemon_sprite(-1, False)["available"])
            sprite = editor.api_pokemon_sprite(25, False)
            self.assertTrue(sprite["available"])
            self.assertEqual((sprite["width"], sprite["height"]), (64, 64))
            with self.assertRaises(ValueError):
                editor._sprite_resource_offset(b"\0" * 4, editor.FRONT_SPRITE_TABLE_OFFSET, 25)
            with self.assertRaises(ValueError):
                editor._sprite_resource_offset(b"\0" * 100, 0, 0)
            self.assertEqual(editor._gba_lz77_decompress(bytes([0x10, 0x02, 0x00, 0x00, 0x00, 1, 2]), 0), b"\x01\x02")
            self.assertEqual(editor._gba_lz77_decompress(bytes([0x10, 0x04, 0x00, 0x00, 0x40, 7, 0, 0]), 0), b"\x07\x07\x07\x07")
            with self.assertRaises(ValueError):
                editor._gba_lz77_decompress(bytes([0, 0, 0, 0]), 0)
            for payload in (
                b"\x10",
                bytes([0x10, 0x01, 0x00, 0x00]),
                bytes([0x10, 0x03, 0x00, 0x00, 0x80, 0]),
                bytes([0x10, 0x03, 0x00, 0x00, 0x80, 0, 5]),
                bytes([0x10, 0x02, 0x00, 0x00, 0x00, 1]),
            ):
                with self.assertRaises(ValueError):
                    editor._gba_lz77_decompress(payload, 0)
            pixels = editor._decode_4bpp_64x64(bytes([0x21] * 32))
            self.assertEqual(pixels[0:2], b"\x01\x02")
            palette = editor._decode_gba_palette_16(bytes(range(32)))
            rgba = editor._pixels_to_rgba(bytes([0, 1, 2]), palette)
            self.assertEqual(len(rgba), 12)
            with self.assertRaises(ValueError):
                editor._decode_gba_palette_16(b"\0")

    def test_pokemon_crypto_validation_and_format_helpers(self) -> None:
        raw = build_pokemon_raw(size=core.PARTY_SIZE, personality=0x12345678, ot_id=0x87654321, species=25)
        pokemon = core.parse_pokemon(raw, 1)
        self.assertEqual(pokemon.species_name, "皮卡丘")
        self.assertEqual(pokemon.held_item_name, "空")
        self.assertIn(pokemon.nature_name, core.NATURE_NAMES)
        self.assertTrue(pokemon.caught_ball_name)
        self.assertFalse(pokemon.is_empty)
        decrypted = core.decrypt_substructures(raw)
        parts = core.split_substructures(pokemon.personality, decrypted)
        self.assertEqual(core.join_substructures(pokemon.personality, parts), decrypted)
        edited = core.edit_pokemon(raw, {"is_egg": True, "ivs": [31, 31, 31, 31, 31, 31], "ability_bit": 1})
        edited_pokemon = core.parse_pokemon(edited, 1)
        self.assertTrue(edited_pokemon.is_egg)
        self.assertEqual(edited_pokemon.ivs, [31, 31, 31, 31, 31, 31])
        self.assertEqual(edited_pokemon.checksum_stored, edited_pokemon.checksum_calculated)
        self.assertEqual(core.format_species(25), "皮卡丘")
        self.assertEqual(core.format_item(0), "空")
        self.assertTrue(core.format_move(33))
        self.assertTrue(core.validate_pokemon(pokemon, "队伍 1"))
        with self.assertRaises(ValueError):
            core.parse_pokemon(b"\0")
        with self.assertRaises(ValueError):
            core.adjust_personality(0x12345678, 0x87654321, 25, gender="雌")

    def test_http_handler_routes_and_error_responses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_path = Path(tmp) / "sample.sav"
            write_save_fixture(save_path)
            server = editor.ThreadingHTTPServer((editor.HOST, editor.available_port(editor.HOST, 8890)), editor.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address
            try:
                status, _headers, _body = self.http_request(host, port, "GET", f"/?save={quote(str(save_path))}")
                self.assertEqual(status, 200)
                status, _headers, body = self.http_request(host, port, "GET", "/api/state")
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(body)["ok"])
                status, _headers, body = self.http_request(host, port, "GET", "/api/names")
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(body)["ok"])
                status, _headers, body = self.http_request(host, port, "GET", "/api/load")
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(body)["ok"])
                with mock.patch("web_save_editor.api_pick_save", return_value={"ok": True, "path": "picked"}):
                    status, _headers, body = self.http_request(host, port, "GET", "/api/pick_save")
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(body)["ok"])
                for path in (
                    "/api/pokemon_constraints?species=25&level=10",
                    "/api/experience_level?species=25&level=10&experience=0",
                    "/api/personality_preview?species=25&personality=1&ot_id=2",
                    "/api/personality_adjust?species=25&personality=1&ot_id=2&nature_id=1&gender=%E6%97%A0%E6%80%A7%E5%88%AB&is_shiny=0",
                    "/api/pokemon_sprite?species=999&shiny=0",
                ):
                    status, _headers, body = self.http_request(host, port, "GET", path)
                    self.assertEqual(status, 200)
                    self.assertIn("ok", json.loads(body))
                for path in (
                    "/api/personality_adjust?species=x",
                    "/api/pokemon_sprite?species=x",
                ):
                    status, _headers, body = self.http_request(host, port, "GET", path)
                    self.assertEqual(status, 400)
                    self.assertFalse(json.loads(body)["ok"])
                status, _headers, body = self.http_request(
                    host,
                    port,
                    "POST",
                    "/api/bag",
                    json.dumps({"pocket": "电脑道具", "slot": 1, "item_id": 13, "quantity": 9}),
                )
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(body)["ok"])
                status, _headers, body = self.http_request(
                    host,
                    port,
                    "POST",
                    "/api/pokemon",
                    json.dumps({
                        "location": "party",
                        "slot": 1,
                        "species": 25,
                        "held_item": 13,
                        "friendship": 70,
                        "nature_id": 1,
                        "gender": "无性别",
                        "is_shiny": 0,
                        "caught_ball": 4,
                        "moves": [33, 45, 0, 0],
                        "pps": [35, 30, 0, 0],
                        "evs": [0, 0, 0, 0, 0, 0],
                        "ivs": [1, 2, 3, 4, 5, 6],
                        "ability_bit": 0,
                        "is_egg": 0,
                        "level": 13,
                    }),
                )
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(body)["ok"])
                status, _headers, body = self.http_request(host, port, "POST", "/api/save", "{}")
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(body)["ok"])
                status, _headers, body = self.http_request(host, port, "POST", "/api/close", "{}")
                self.assertEqual(status, 200)
                self.assertFalse(json.loads(body)["ok"])
                status, _headers, body = self.http_request(host, port, "POST", "/api/bag", "{}")
                self.assertEqual(status, 400)
                self.assertFalse(json.loads(body)["ok"])
                status, _headers, body = self.http_request(host, port, "GET", "/missing")
                self.assertEqual(status, 404)
                self.assertEqual(body, "Not found")
                status, _headers, body = self.http_request(host, port, "GET", "/api/personality_preview?species=x")
                self.assertEqual(status, 400)
                self.assertFalse(json.loads(body)["ok"])
                status, _headers, body = self.http_request(host, port, "POST", "/api/bag", "{")
                self.assertEqual(status, 400)
                self.assertFalse(json.loads(body)["ok"])
                status, _headers, body = self.http_request(host, port, "POST", "/missing", "{}")
                self.assertEqual(status, 404)
                self.assertEqual(body, "Not found")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_core_error_paths_and_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            small = Path(tmp) / "small.sav"
            small.write_bytes(b"\0" * 10)
            with self.assertRaises(core.SaveFormatError):
                core.EmeraldSave(small)
            save_path = Path(tmp) / "sample.sav"
            write_save_fixture(save_path)
            save = core.EmeraldSave(save_path)
            with self.assertRaises(ValueError):
                save._read_box_storage_range(-1, 1)
            with self.assertRaises(ValueError):
                save._write_box_storage_range(core.BOX_DATA_OFFSET + core.BOX_DATA_SIZE, b"x")
            self.assertEqual(core.tmhm_move_for_item(1), None)
            self.assertEqual(core.default_pp_for_move(9999), 0)
            self.assertEqual(core.gender_for_species(9999, 1), "无性别")
            self.assertEqual(core.ability_options_for_species(9999), [])
            self.assertEqual(core.gender_options_for_species(9999), ["无性别"])
            self.assertIsNone(core.growth_rate_for_species(9999))
            self.assertEqual(core.pre_evolution_species_ids(9999), [])
            self.assertEqual(core.move_legality_for_species(25, 5, 0).sources, ["空"])

    def test_additional_branch_coverage_for_core_and_web_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_path = Path(tmp) / "sample.sav"
            write_save_fixture(save_path)
            self.assertEqual(editor.table_sort_rank("unknown"), 9)
            editor.load_save(None)
            self.assertFalse(editor.api_state()["ok"])
            gba = save_path.with_suffix(".GBA")
            gba.write_bytes(b"rom")
            self.assertEqual(editor.find_matching_rom(save_path).suffix.lower(), ".gba")
            self.assertEqual(editor.response({"ok": True})[0], 200)
            self.assertEqual(editor.query_int({}, "missing", 7), 7)
            with self.assertRaises(ValueError):
                editor.query_int({"x": ["bad"]}, "x")

            with mock.patch("web_save_editor.subprocess.run", side_effect=subprocess.CalledProcessError(1, "osascript")):
                self.assertFalse(editor.api_pick_save()["ok"])
            with mock.patch("web_save_editor.subprocess.run", return_value=mock.Mock(stdout=str(save_path) + "\n")):
                self.assertTrue(editor.api_pick_save()["ok"])

            sample_raw = {
                "species": {"25": {"name": "皮卡丘", "decoded": "皮卡丘", "tokens": ["01"], "detail": {"types": ["电"]}}},
                "moves": {"33": {"name": "撞击", "decoded": "{AA}", "tokens": ["AA"], "pp": 0, "description": "撞"}},
                "abilities": {"1": {"name": "恶臭", "decoded": "恶臭", "tokens": ["02"]}},
                "items": {"13": {"name": "伤药", "decoded": "伤药", "tokens": ["03"], "detail": {"price": 300}}},
                "character_map_count": 10,
                "rom_used_character_key_count": 3,
                "rom_unknown_character_key_count": 1,
                "used_character_keys": [{"code": "AA", "known": False}],
            }
            editor.STATE.rom_path = save_path
            editor.STATE.save = core.EmeraldSave(save_path)
            with mock.patch("web_save_editor.extract_rom_text", return_value=sample_raw):
                names = editor.api_names()
            self.assertEqual(names["stats"]["charmap"]["rom_unknown"], 1)
            self.assertEqual(names["moves"][0]["unknown_count"], 1)
            self.assertTrue(editor.dictionary_table_info()["species"]["description"])

            with mock.patch("pokemon_save_core._extract_rom_dictionary", return_value={
                "species": {"bad": {}, "77": {"name": ""}},
                "items": {"88": {"decoded": ""}},
                "moves": {"99": {"name": "测试招式"}},
                "abilities": {"7": {"decoded": "测试特性"}},
            }):
                core.reload_rom_names()
            self.assertEqual(core.SPECIES_NAMES[77], "species 77")
            self.assertEqual(core.ITEM_NAMES[88], "items 88")
            self.assertEqual(core.MOVE_NAMES[99], "测试招式")
            self.assertEqual(core.ABILITY_NAMES[7], "测试特性")

            save = core.EmeraldSave(save_path)
            core.ITEM_NAMES[13] = "伤药"
            self.assertEqual(core.BagEntry("电脑道具", 1, 13, 1).item_name, "伤药")
            nonzero = core.parse_pokemon(build_pokemon_raw(size=core.PARTY_SIZE, personality=0x44445555, ot_id=1, species=25, held_item=999))
            self.assertIn("999", nonzero.held_item_name)
            stats = bytearray(28)
            stats[22] = 9
            core.BASE_STATS[25] = bytes(stats)
            ability = core.parse_pokemon(build_pokemon_raw(size=core.PARTY_SIZE, personality=0x11112222, ot_id=1, species=25))
            self.assertIn("特性", ability.ability_name)

            data = bytearray(save_path.read_bytes())
            _w32(data, core.SAVE_BLOCK_SIZE + 0x0FF8, 0)
            one_block = Path(tmp) / "one-block.sav"
            one_block.write_bytes(data)
            self.assertEqual(core.EmeraldSave(one_block).active_base, 0)
            invalid = Path(tmp) / "invalid.sav"
            invalid.write_bytes(b"\0" * 0x20000)
            with self.assertRaises(core.SaveFormatError):
                core.EmeraldSave(invalid)

            read_offset = core.SECTION_CHECKSUM_SIZES[5] + 1
            self.assertEqual(len(save._read_box_storage_range(read_offset, 8)), 8)
            self.assertTrue(save._write_box_storage_range(read_offset, b"12345678"))
            with self.assertRaises(ValueError):
                save.update_box_pokemon(1, 99, {})
            edited = core.edit_pokemon(build_pokemon_raw(size=core.PARTY_SIZE, personality=0x12345678, ot_id=1, species=25), {
                "personality": 0x11111111,
                "experience": 12345,
                "current_hp": 1,
            })
            edited_pokemon = core.parse_pokemon(edited)
            self.assertEqual(edited_pokemon.personality, 0x11111111)
            self.assertEqual(edited_pokemon.experience, 12345)
            self.assertEqual(edited_pokemon.current_hp, 1)
            with self.assertRaises(ValueError):
                core.join_substructures(0, {"G": bytearray(1), "A": bytearray(12), "E": bytearray(12), "M": bytearray(12)})

    def test_validation_and_pre_evolution_branches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rom_path = Path(tmp) / "sample.gba"
            fake_rom(rom_path)
            core.set_rom_path(rom_path)
            editor.configure_rom(rom_path)
            pre = editor.api_pokemon_constraints(26, 10)
            self.assertTrue(any("前置" in source for row in pre["moves"] for source in row["sources"]))
            future = editor.api_pokemon_constraints(26, 1)
            self.assertTrue(future["future_moves"] or future["moves"])

            save_path = Path(tmp) / "sample.sav"
            write_save_fixture(save_path)
            save = core.EmeraldSave(save_path)
            save.sections[save.active_base].pop(0)
            messages = save.validate()
            self.assertTrue(any("section 不完整" in message for message in messages))

            save = core.EmeraldSave(save_path)
            ref = save.sections[save.active_base][0]
            save.sections[save.active_base][0] = core.SectionRef(ref.block_base, ref.section_offset, ref.section_id, ref.save_index + 1)
            self.assertTrue(any("save index 不一致" in message for message in save.validate()))

            save = core.EmeraldSave(save_path)
            off = save.section_ref(0).absolute_offset
            save.data[off] ^= 0xFF
            self.assertTrue(any("校验错误" in message for message in save.validate()))

    def http_request(self, host: str, port: int, method: str, path: str, body: str | None = None):
        conn = http.client.HTTPConnection(host, port, timeout=10)
        try:
            headers = {"Content-Type": "application/json"} if body is not None else {}
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            payload = response.read().decode("utf-8")
            return response.status, dict(response.getheaders()), payload
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
