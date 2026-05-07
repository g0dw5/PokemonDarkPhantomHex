from __future__ import annotations

import base64
import json
import socket
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pokemon_save_core import (
    BagEntry,
    EmeraldSave,
    BALL_NAMES,
    ITEM_NAMES,
    MOVE_NAMES,
    NATURE_NAMES,
    SPECIES_NAMES,
    ABILITY_NAMES,
    constraints_for_species,
    default_pp_for_move,
    format_item,
    format_move,
    format_species,
    validate_pokemon,
    rom_constraints_loaded,
    set_rom_path,
    growth_rate_for_species,
    experience_for_level,
    level_for_experience,
    gender_for_species,
    species_type_names,
    is_shiny,
    adjust_personality,
)
from rom_data import extract_rom_text, is_placeholder_text, set_default_rom_path


DEFAULT_SAVE = None
HOST = "127.0.0.1"
PORT = 8765
GBA_ROM_POINTER_BASE = 0x08000000
FRONT_SPRITE_TABLE_OFFSET = 0x30A18C
NORMAL_PALETTE_TABLE_OFFSET = 0x303678
SHINY_PALETTE_TABLE_OFFSET = 0x304438
SPRITE_TABLE_ENTRY_SIZE = 8
SPRITE_TABLE_COUNT = 440
SPRITE_WIDTH = 64
SPRITE_HEIGHT = 64
SPRITE_PIXEL_COUNT = SPRITE_WIDTH * SPRITE_HEIGHT


class State:
    save_path: Path | None = DEFAULT_SAVE
    rom_path: Path | None = None
    save: EmeraldSave | None = None
    dirty = False
    changes: list[str] = []
    error = "请选择存档文件"


STATE = State()


def table_sort_rank(table: str) -> int:
    return {"species": 0, "abilities": 1, "moves": 2, "items": 3, "natures": 4, "balls": 5}.get(table, 9)


def load_save(path: Path | None = None) -> None:
    if path is not None:
        STATE.save_path = path
    if STATE.save_path is None:
        STATE.save = None
        STATE.rom_path = None
        STATE.dirty = False
        STATE.changes = []
        configure_rom(None)
        STATE.error = "请选择存档文件"
        return
    try:
        STATE.save = EmeraldSave(STATE.save_path)
        configure_rom(find_matching_rom(STATE.save_path))
        STATE.dirty = False
        STATE.changes = []
        STATE.error = ""
    except Exception as exc:
        STATE.save = None
        STATE.rom_path = None
        STATE.dirty = False
        STATE.changes = []
        configure_rom(None)
        STATE.error = str(exc)


def find_matching_rom(save_path: Path) -> Path | None:
    for suffix in (".gba", ".GBA"):
        candidate = save_path.with_suffix(suffix)
        if candidate.exists():
            return candidate
    return None


def configure_rom(path: Path | None) -> None:
    STATE.rom_path = path
    set_rom_path(path)
    set_default_rom_path(path)


def response(payload, status=200):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return status, "application/json; charset=utf-8", data


def query_int(query, name: str, default: int = 0) -> int:
    value = query.get(name, [str(default)])[0]
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"参数 {name} 不是有效整数：{value}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            query = parse_qs(parsed.query)
            if query.get("save", [""])[0]:
                load_save(Path(query["save"][0]).expanduser())
            self.send(200, "text/html; charset=utf-8", HTML.encode("utf-8"))
            return
        if parsed.path == "/api/state":
            self.send(*response(api_state()))
            return
        if parsed.path == "/api/names":
            self.send(*response(api_names()))
            return
        if parsed.path == "/api/pokemon_constraints":
            query = parse_qs(parsed.query)
            species = int(query.get("species", ["0"])[0])
            level = int(query.get("level", ["1"])[0])
            self.send(*response(api_pokemon_constraints(species, level)))
            return
        if parsed.path == "/api/experience_level":
            query = parse_qs(parsed.query)
            species = int(query.get("species", ["0"])[0])
            level = int(query.get("level", ["1"])[0])
            experience = int(query.get("experience", ["0"])[0])
            self.send(*response(api_experience_level(species, level, experience)))
            return
        if parsed.path == "/api/personality_preview":
            try:
                query = parse_qs(parsed.query)
                species = query_int(query, "species")
                personality = query_int(query, "personality")
                ot_id = query_int(query, "ot_id")
                self.send(*response(api_personality_preview(species, personality, ot_id)))
            except ValueError as error:
                self.send(*response({"ok": False, "error": str(error)}, 400))
            return
        if parsed.path == "/api/personality_adjust":
            try:
                query = parse_qs(parsed.query)
                species = query_int(query, "species")
                personality = query_int(query, "personality")
                ot_id = query_int(query, "ot_id")
                nature_id = query_int(query, "nature_id")
                gender = query.get("gender", [""])[0]
                shiny = bool(query_int(query, "is_shiny"))
                self.send(*response(api_personality_adjust(species, personality, ot_id, nature_id, gender, shiny)))
            except ValueError as error:
                self.send(*response({"ok": False, "error": str(error)}, 400))
            return
        if parsed.path == "/api/pokemon_sprite":
            try:
                query = parse_qs(parsed.query)
                species = query_int(query, "species")
                shiny = bool(query_int(query, "shiny", 0))
                self.send(*response(api_pokemon_sprite(species, shiny)))
            except ValueError as error:
                self.send(*response({"ok": False, "error": str(error)}, 400))
            return
        if parsed.path == "/api/load":
            query = parse_qs(parsed.query)
            raw_path = query.get("path", [""])[0] or (str(STATE.save_path) if STATE.save_path else "")
            path = Path(raw_path).expanduser() if raw_path else None
            load_save(path)
            self.send(*response(api_state()))
            return
        if parsed.path == "/api/pick_save":
            self.send(*response(api_pick_save()))
            return
        self.send(404, "text/plain; charset=utf-8", b"Not found")

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self.send(*response({"ok": False, "error": "JSON 格式错误"}, 400))
            return
        try:
            if self.path == "/api/bag":
                self.send(*response(api_update_bag(body)))
                return
            if self.path == "/api/pokemon":
                self.send(*response(api_update_pokemon(body)))
                return
            if self.path == "/api/save":
                self.send(*response(api_save()))
                return
            if self.path == "/api/close":
                self.send(*response(api_close()))
                return
        except Exception as exc:
            self.send(*response({"ok": False, "error": str(exc)}, 400))
            return
        self.send(404, "text/plain; charset=utf-8", b"Not found")

    def send(self, status: int, content_type: str, data: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            return


def api_state():
    save = STATE.save
    if not save:
        return {"ok": False, "dirty": STATE.dirty, "changes": STATE.changes, "path": str(STATE.save_path) if STATE.save_path else "", "rom_path": str(STATE.rom_path) if STATE.rom_path else "", "error": STATE.error, "bag": [], "party": [], "validation": []}
    bag = [{"pocket": e.pocket, "slot": e.slot, "item_id": e.item_id, "name": format_item(e.item_id) if e.item_id else "空", "quantity": e.quantity} for e in save.read_bag()]
    party = []
    for p in save.party():
        party.append(pokemon_payload(p, f"队伍 {p.slot}"))
    boxes = [pokemon_payload(p, f"盒子 {p.box}-{p.box_slot}") for p in save.boxes()]
    active = "A" if save.active_base == 0 else "B"
    bag_by_pocket = {}
    for entry in bag:
        stats = bag_by_pocket.setdefault(entry["pocket"], {"total": 0, "filled": 0})
        stats["total"] += 1
        if entry["item_id"] or entry["quantity"]:
            stats["filled"] += 1
    boxes_by_box = {}
    for pokemon in boxes:
        stats = boxes_by_box.setdefault(str(pokemon["box"]), {"total": 30, "filled": 0})
        stats["filled"] += 1
    return {
        "ok": True,
        "dirty": STATE.dirty,
        "changes": STATE.changes,
        "path": str(save.path),
        "rom_path": str(STATE.rom_path) if STATE.rom_path else "",
        "active": active,
        "security_key": f"0x{save.security_key():08X}",
        "trainer": save.trainer_summary(),
        "inventory": save.inventory_summary(),
        "bag": bag,
        "bag_by_pocket": bag_by_pocket,
        "party": party,
        "boxes": boxes,
        "boxes_by_box": boxes_by_box,
        "sections": save.section_summary(),
        "validation": save.validate(),
        "name_counts": {
            "species": len(SPECIES_NAMES),
            "moves": len(MOVE_NAMES),
            "abilities": len(ABILITY_NAMES),
            "items": len(ITEM_NAMES),
        },
    }


def api_pick_save():
    try:
        result = subprocess.run(
            ["osascript", "-e", 'POSIX path of (choose file with prompt "选择存档文件")'],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return {"ok": False, "path": str(STATE.save_path) if STATE.save_path else "", "error": "已取消选择"}
    path = Path(result.stdout.strip()).expanduser()
    load_save(path)
    return api_state()


def pokemon_payload(p, label: str):
    return {
        "slot": p.slot,
        "box": p.box,
        "box_slot": p.box_slot,
        "species": p.species,
        "species_name": p.species_name,
        "types": species_type_names(p.species),
        "personality": p.personality,
        "ot_id": p.ot_id,
        "held_item": p.held_item,
        "held_item_name": format_item(p.held_item) if p.held_item else "空",
        "nature_id": p.nature_id,
        "nature_name": p.nature_name,
        "gender": p.gender,
        "is_shiny": p.is_shiny,
        "caught_ball": p.caught_ball,
        "caught_ball_name": p.caught_ball_name,
        "ability_id": p.ability_id,
        "ability_name": p.ability_name,
        "experience": p.experience,
        "friendship": p.friendship,
        "level": p.level,
        "current_hp": p.current_hp,
        "max_hp": p.max_hp,
        "moves": p.moves,
        "move_names": [format_move(move_id) if move_id else "空" for move_id in p.moves],
        "pps": p.pps,
        "evs": p.evs,
        "ivs": p.ivs,
        "ability_bit": p.ability_bit,
        "is_egg": p.is_egg,
        "checksum_ok": p.checksum_stored == p.checksum_calculated,
        "legality": validate_pokemon(p, label, check_level=not p.box, move_level=(p.level or 100) if p.box else None),
    }


def api_names():
    if STATE.rom_path and STATE.rom_path.exists():
        raw = extract_rom_text(STATE.rom_path)
    else:
        raw = {
            "species": {},
            "moves": {},
            "abilities": {},
            "items": {},
            "character_map_count": 0,
            "rom_used_character_key_count": 0,
            "rom_unknown_character_key_count": 0,
            "used_character_keys": [],
            "text_model": {},
        }
    observed = observed_from_save()

    def table(name: str, label: str):
        rows = []
        for key, entry in sorted(raw.get(name, {}).items(), key=lambda item: int(item[0])):
            item_id = int(key)
            if name == "species" and item_id == 0:
                continue
            tokens = entry.get("tokens") or []
            row_name = entry.get("name") or ""
            decoded = entry.get("decoded") or ""
            description = entry.get("description") or ""
            detail = dict(entry.get("detail") or {})
            if name == "items":
                if is_placeholder_text(row_name or decoded):
                    row_name = format_item(item_id)
                    decoded = row_name
                if is_placeholder_text(description):
                    description = ""
                if is_placeholder_text(detail.get("description")):
                    detail["description"] = ""
            visible_name = row_name or decoded
            generic_label = {"moves": "招式", "abilities": "特性", "items": "道具"}.get(name)
            if generic_label and (item_id == 0 or visible_name == f"{generic_label} {item_id}"):
                continue
            row = {
                "table": name,
                "table_label": label,
                "id": item_id,
                "name": row_name,
                "decoded": decoded,
                "tokens": tokens,
                "observed": item_id in observed[name],
                "locations": observed[name].get(item_id, []),
                "unknown_count": sum(1 for token in tokens if "{" + token + "}" in (entry.get("decoded") or "")),
                "description": description,
                "detail": detail,
                "raw_hex": entry.get("raw_hex") or "",
            }
            if name == "moves":
                row["pp"] = entry.get("pp") or default_pp_for_move(item_id)
            rows.append(row)
        return rows

    static_rows = []
    for nature_id, name in enumerate(NATURE_NAMES):
        static_rows.append({
            "table": "natures",
            "table_label": "性格",
            "id": nature_id,
            "name": name,
            "observed": nature_id in observed["natures"],
            "locations": observed["natures"].get(nature_id, []),
        })
    for ball_id, name in sorted(BALL_NAMES.items()):
        static_rows.append({
            "table": "balls",
            "table_label": "球",
            "id": ball_id,
            "name": name,
            "observed": ball_id in observed["balls"],
            "locations": observed["balls"].get(ball_id, []),
        })
    save = STATE.save
    species_rows = table("species", "宝可梦")
    move_rows = table("moves", "招式")
    ability_rows = table("abilities", "特性")
    item_rows = table("items", "道具")
    rows = [*species_rows, *move_rows, *ability_rows, *item_rows]
    observed_key_count = count_observed_charmap_keys(rows)
    stats = {
        "rom_loaded": bool(STATE.rom_path and STATE.rom_path.exists()),
        "save_loaded": bool(save),
        "party_count": len(save.party()) if save else 0,
        "box_occupied": len(save.boxes()) if save else 0,
        "box_slots": 14 * 30,
        "bag_filled": sum(1 for entry in save.read_bag() if entry.item_id or entry.quantity) if save else 0,
        "bag_slots": len(save.read_bag()) if save else 0,
        "observed": {key: len(value) for key, value in observed.items()},
        "rom": {
            "species": len(raw.get("species", {})),
            "moves": len(raw.get("moves", {})),
            "abilities": len(raw.get("abilities", {})),
            "items": len(raw.get("items", {})),
        },
        "charmap": {
            "official": int(raw.get("character_map_count", 0)),
            "rom_used": int(raw.get("rom_used_character_key_count", 0)),
            "rom_unknown": int(raw.get("rom_unknown_character_key_count", 0)),
            "rom_unknown_codes": [item.get("code", "") for item in raw.get("used_character_keys", []) if not item.get("known")],
            "observed_keys": observed_key_count,
        },
    }
    return {
        "ok": True,
        "species": species_rows,
        "moves": move_rows,
        "abilities": ability_rows,
        "items": item_rows,
        "stats": stats,
        "rows": sorted(rows, key=lambda row: (table_sort_rank(row["table"]), row["id"])),
        "static_rows": static_rows,
        "table_info": dictionary_table_info(),
    }


def dictionary_table_info() -> dict[str, dict[str, str]]:
    return {
        "species": {
            "label": "宝可梦",
            "description": "ROM 种族名称表，并补充 base stats：基础能力、属性、性别比例、经验曲线、蛋组、特性、野生携带道具和野生 Encounter。",
        },
        "moves": {
            "label": "招式",
            "description": "ROM 招式名称表，并补充招式 PP 和招式描述文本。合法可学范围仍由队伍/盒子编辑页的约束接口计算。",
        },
        "abilities": {
            "label": "特性",
            "description": "ROM 特性名称表。基础 0..77 和扩展 78..150 号特性均已定位描述指针并展示说明。",
        },
        "items": {
            "label": "道具",
            "description": "ROM 道具名称表，并补充描述、价格、所属口袋、道具类型、携带效果和内部 secondary id。",
        },
    }


def api_pokemon_constraints(species: int, level: int):
    constraints = constraints_for_species(species)
    if constraints is None:
        return {
            "ok": True,
            "available": False,
            "message": "未加载 ROM 约束数据" if not rom_constraints_loaded() else f"无法读取种族 {species} 的 ROM 约束数据",
            "species": species,
            "level": level,
            "gender_options": [],
            "ability_options": [],
            "moves": [],
            "future_moves": [],
        }
    move_sources: dict[int, set[str]] = {}
    future_levels: dict[int, list[int]] = {}
    future_sources: dict[int, set[str]] = {}
    for move_id, levels in constraints.level_up_moves.items():
        current = [learn_level for learn_level in levels if learn_level <= level]
        future = [learn_level for learn_level in levels if learn_level > level]
        if current:
            move_sources.setdefault(move_id, set()).add(f"升级Lv{'/'.join(str(learn_level) for learn_level in sorted(current))}")
        if future:
            future_levels.setdefault(move_id, []).extend(future)
            future_sources.setdefault(move_id, set()).add(f"Lv{'/'.join(str(learn_level) for learn_level in sorted(future))}可学")
    for move_id, by_species in constraints.pre_evolution_level_up_moves.items():
        for pre_species_id, levels in by_species.items():
            current = [learn_level for learn_level in levels if learn_level <= level]
            future = [learn_level for learn_level in levels if learn_level > level]
            if current:
                move_sources.setdefault(move_id, set()).add(
                    f"前置{format_species(pre_species_id)}Lv{'/'.join(str(learn_level) for learn_level in sorted(current))}"
                )
            if future:
                future_levels.setdefault(move_id, []).extend(future)
                future_sources.setdefault(move_id, set()).add(
                    f"前置{format_species(pre_species_id)}Lv{'/'.join(str(learn_level) for learn_level in sorted(future))}可学"
                )
    for move_id, tmhm_index in constraints.tmhm_moves.items():
        move_sources.setdefault(move_id, set()).add(f"TM/HM{tmhm_index:02d}")
    for move_id, tutor_index in constraints.tutor_moves.items():
        move_sources.setdefault(move_id, set()).add(f"定点教学{tutor_index:02d}")
    for move_id in constraints.egg_moves:
        move_sources.setdefault(move_id, set()).add("遗传")
    for move_id, pre_species_ids in constraints.pre_evolution_egg_moves.items():
        for pre_species_id in pre_species_ids:
            move_sources.setdefault(move_id, set()).add(f"前置{format_species(pre_species_id)}遗传")

    def move_sort_key(item: tuple[int, set[str]]):
        move_id, sources = item
        if any(source.startswith("升级Lv") for source in sources):
            current_levels = [learn_level for learn_level in constraints.level_up_moves.get(move_id, []) if learn_level <= level]
            first_level = min(current_levels) if current_levels else 101
            rank = (0, first_level)
        elif any(source.startswith("TM/HM") for source in sources):
            rank = (1, constraints.tmhm_moves.get(move_id, 999))
        elif any(source.startswith("定点教学") for source in sources):
            rank = (2, constraints.tutor_moves.get(move_id, 999))
        elif "遗传" in sources:
            rank = (3, move_id)
        elif any(source.endswith("遗传") for source in sources):
            rank = (4, move_id)
        else:
            rank = (9, move_id)
        return (*rank, move_id)

    moves = []
    for move_id, sources in sorted(move_sources.items(), key=move_sort_key):
        moves.append(
            {
                "id": move_id,
                "name": format_move(move_id),
                "sources": sorted(sources),
                "current_levels": sorted(learn_level for learn_level in constraints.level_up_moves.get(move_id, []) if learn_level <= level),
                "future_levels": sorted(set(future_levels.get(move_id, []))),
                "pp": default_pp_for_move(move_id),
                "disabled": False,
            }
        )
    future_moves = [
        {
            "id": move_id,
            "name": format_move(move_id),
            "sources": sorted(future_sources.get(move_id, {f"Lv{'/'.join(str(level) for level in levels)}可学"})),
            "current_levels": [],
            "future_levels": sorted(set(levels)),
            "pp": default_pp_for_move(move_id),
            "disabled": True,
        }
        for move_id, levels in sorted(future_levels.items(), key=lambda item: (min(item[1]), item[0]))
        if move_id not in move_sources
    ]
    return {
        "ok": True,
        "available": True,
        "species": species,
        "level": level,
        "gender_options": constraints.gender_options,
        "ability_options": [
            {"bit": bit, "id": ability_id, "name": ABILITY_NAMES.get(ability_id, f"特性 {ability_id}")}
            for bit, ability_id in constraints.ability_options
        ],
        "moves": moves,
        "future_moves": future_moves,
    }


def api_experience_level(species: int, level: int, experience: int):
    growth_rate = growth_rate_for_species(species)
    if growth_rate is None:
        return {
            "ok": True,
            "available": False,
            "message": "未加载 ROM 经验曲线数据",
            "species": species,
            "level": level,
            "experience": experience,
        }
    return {
        "ok": True,
        "available": True,
        "species": species,
        "growth_rate": growth_rate,
        "level": level_for_experience(species, experience),
        "experience": experience_for_level(growth_rate, level),
    }


def api_personality_preview(species: int, personality: int, ot_id: int):
    return {
        "ok": True,
        "species": species,
        "personality": personality,
        "nature_id": personality % 25,
        "gender": gender_for_species(species, personality),
        "is_shiny": is_shiny(personality, ot_id),
    }


def api_personality_adjust(species: int, personality: int, ot_id: int, nature_id: int, gender: str, shiny: bool):
    target = adjust_personality(personality, ot_id, species, nature_id=nature_id, gender=gender, shiny=shiny)
    return api_personality_preview(species, target, ot_id)


def api_pokemon_sprite(species: int, shiny: bool):
    if not (0 <= species < SPRITE_TABLE_COUNT):
        return {
            "ok": True,
            "available": False,
            "species": species,
            "shiny": shiny,
            "message": f"种族 {species} 不在图像槽范围 0..{SPRITE_TABLE_COUNT - 1}",
        }
    if STATE.rom_path is None or not STATE.rom_path.exists():
        return {"ok": True, "available": False, "species": species, "shiny": shiny, "message": "未加载同名 ROM，无法读取图像"}
    try:
        rom = STATE.rom_path.read_bytes()
    except OSError as exc:
        return {"ok": True, "available": False, "species": species, "shiny": shiny, "message": f"读取 ROM 失败：{exc}"}
    try:
        sprite_offset = _sprite_resource_offset(rom, FRONT_SPRITE_TABLE_OFFSET, species)
        palette_table_offset = SHINY_PALETTE_TABLE_OFFSET if shiny else NORMAL_PALETTE_TABLE_OFFSET
        palette_offset = _sprite_resource_offset(rom, palette_table_offset, species)
        sprite_data = _gba_lz77_decompress(rom, sprite_offset)
        palette_data = _gba_lz77_decompress(rom, palette_offset)
        pixels = _decode_4bpp_64x64(sprite_data)
        palette = _decode_gba_palette_16(palette_data)
        rgba = _pixels_to_rgba(pixels, palette)
    except ValueError as exc:
        return {"ok": True, "available": False, "species": species, "shiny": shiny, "message": str(exc)}
    return {
        "ok": True,
        "available": True,
        "species": species,
        "shiny": shiny,
        "width": SPRITE_WIDTH,
        "height": SPRITE_HEIGHT,
        "rgba_base64": base64.b64encode(rgba).decode("ascii"),
    }


def _sprite_resource_offset(rom: bytes, table_offset: int, species: int) -> int:
    entry_offset = table_offset + species * SPRITE_TABLE_ENTRY_SIZE
    if entry_offset + SPRITE_TABLE_ENTRY_SIZE > len(rom):
        raise ValueError(f"ROM 太小，无法读取种族 {species} 图像索引")
    pointer = int.from_bytes(rom[entry_offset : entry_offset + 4], "little")
    offset = pointer - GBA_ROM_POINTER_BASE
    if not (0 <= offset < len(rom)):
        raise ValueError(f"ROM 图像指针非法：species {species}, ptr=0x{pointer:08X}")
    return offset


def _gba_lz77_decompress(rom: bytes, offset: int) -> bytes:
    if offset + 4 > len(rom):
        raise ValueError(f"LZ77 头超出范围：0x{offset:08X}")
    if rom[offset] != 0x10:
        raise ValueError(f"LZ77 头标记错误：0x{offset:08X}")
    output_size = rom[offset + 1] | (rom[offset + 2] << 8) | (rom[offset + 3] << 16)
    src = offset + 4
    out = bytearray()
    while len(out) < output_size:
        if src >= len(rom):
            raise ValueError(f"LZ77 数据截断：0x{offset:08X}")
        flags = rom[src]
        src += 1
        for _ in range(8):
            if len(out) >= output_size:
                break
            if flags & 0x80:
                if src + 1 >= len(rom):
                    raise ValueError(f"LZ77 回溯块截断：0x{offset:08X}")
                first = rom[src]
                second = rom[src + 1]
                src += 2
                length = (first >> 4) + 3
                displacement = ((first & 0x0F) << 8) | second
                copy_from = len(out) - displacement - 1
                if copy_from < 0:
                    raise ValueError(f"LZ77 回溯位移无效：0x{offset:08X}")
                for _ in range(length):
                    out.append(out[copy_from])
                    copy_from += 1
                    if len(out) >= output_size:
                        break
            else:
                if src >= len(rom):
                    raise ValueError(f"LZ77 原样块截断：0x{offset:08X}")
                out.append(rom[src])
                src += 1
            flags = (flags << 1) & 0xFF
    return bytes(out)


def _decode_4bpp_64x64(data: bytes) -> bytes:
    tile_bytes = 32
    tiles_per_row = SPRITE_WIDTH // 8
    max_tiles = (SPRITE_WIDTH // 8) * (SPRITE_HEIGHT // 8)
    tiles = min(len(data) // tile_bytes, max_tiles)
    pixels = bytearray(SPRITE_PIXEL_COUNT)
    for tile_index in range(tiles):
        tile_base = tile_index * tile_bytes
        tile_x = tile_index % tiles_per_row
        tile_y = tile_index // tiles_per_row
        for row in range(8):
            row_base = tile_base + row * 4
            y = tile_y * 8 + row
            pixel_base = y * SPRITE_WIDTH + tile_x * 8
            for col_pair in range(4):
                value = data[row_base + col_pair]
                pixels[pixel_base + col_pair * 2] = value & 0x0F
                pixels[pixel_base + col_pair * 2 + 1] = (value >> 4) & 0x0F
    return bytes(pixels)


def _decode_gba_palette_16(data: bytes) -> list[tuple[int, int, int]]:
    if len(data) < 0x20:
        raise ValueError("调色板解压长度不足 0x20")
    palette: list[tuple[int, int, int]] = []
    for index in range(16):
        color = int.from_bytes(data[index * 2 : index * 2 + 2], "little")
        r5 = color & 0x1F
        g5 = (color >> 5) & 0x1F
        b5 = (color >> 10) & 0x1F
        r = (r5 * 255) // 31
        g = (g5 * 255) // 31
        b = (b5 * 255) // 31
        palette.append((r, g, b))
    return palette


def _pixels_to_rgba(pixels: bytes, palette: list[tuple[int, int, int]]) -> bytes:
    rgba = bytearray(len(pixels) * 4)
    for idx, color_index in enumerate(pixels):
        r, g, b = palette[color_index]
        alpha = 0 if color_index == 0 else 255
        out = idx * 4
        rgba[out] = r
        rgba[out + 1] = g
        rgba[out + 2] = b
        rgba[out + 3] = alpha
    return bytes(rgba)


def observed_from_save() -> dict[str, dict[int, list[str]]]:
    observed: dict[str, dict[int, list[str]]] = {"species": {}, "items": {}, "moves": {}, "abilities": {}, "natures": {}, "balls": {}}
    save = STATE.save
    if not save:
        return observed
    for entry in save.read_bag():
        if entry.item_id:
            add_observed(observed["items"], entry.item_id, f"{entry.pocket} #{entry.slot} x{entry.quantity}")
    for pokemon in [*save.party(), *save.boxes()]:
        location = f"队伍 #{pokemon.slot}" if not pokemon.box else f"盒子 {pokemon.box}-{pokemon.box_slot}"
        if pokemon.species:
            add_observed(observed["species"], pokemon.species, location)
        if pokemon.held_item:
            add_observed(observed["items"], pokemon.held_item, f"{location} 携带")
        if pokemon.ability_id:
            add_observed(observed["abilities"], pokemon.ability_id, location)
        add_observed(observed["natures"], pokemon.nature_id, location)
        add_observed(observed["balls"], pokemon.caught_ball, location)
        for move_id in pokemon.moves:
            if move_id:
                add_observed(observed["moves"], move_id, location)
    return observed


def add_observed(bucket: dict[int, list[str]], item_id: int, location: str) -> None:
    locations = bucket.setdefault(item_id, [])
    if location not in locations:
        locations.append(location)


def count_observed_charmap_keys(rows: list[dict]) -> int:
    codes = set()
    for row in rows:
        if not row.get("observed"):
            continue
        codes.update(str(token).upper() for token in row.get("tokens", []))
    return len(codes)


def record_change(message: str, diffs: list[dict] | None = None) -> None:
    STATE.changes.append({"summary": message, "diffs": diffs or []})
    if len(STATE.changes) > 100:
        STATE.changes = STATE.changes[-100:]


def api_update_bag(body):
    save = require_save()
    entry = BagEntry(str(body["pocket"]), int(body["slot"]), int(body["item_id"]), int(body["quantity"]))
    before = next((old for old in save.read_bag() if old.pocket == entry.pocket and old.slot == entry.slot), None)
    save.write_bag_entry(entry)
    STATE.dirty = True
    message = f"已写入背包：{entry.pocket} {entry.slot} = {format_item(entry.item_id)} x{entry.quantity}"
    diffs = []
    if before and before.item_id != entry.item_id:
        diffs.append({"field": "道具", "before": format_item(before.item_id) if before.item_id else "空", "after": format_item(entry.item_id) if entry.item_id else "空"})
    if before and before.quantity != entry.quantity:
        diffs.append({"field": "数量", "before": before.quantity, "after": entry.quantity})
    record_change(message, diffs)
    return {"ok": True, "message": message}


def api_update_pokemon(body):
    save = require_save()
    updates = {
        "species": parse_id(body["species"]),
        "held_item": parse_id(body["held_item"]),
        "friendship": int(body["friendship"]),
        "nature_id": int(body["nature_id"]),
        "gender": str(body["gender"]),
        "is_shiny": bool(int(body["is_shiny"])),
        "caught_ball": int(body["caught_ball"]),
        "moves": parse_list(body["moves"], 4),
        "pps": parse_list(body["pps"], 4),
        "evs": parse_list(body["evs"], 6),
        "ivs": parse_list(body["ivs"], 6),
        "ability_bit": int(body["ability_bit"]),
        "is_egg": bool(int(body["is_egg"])),
    }
    if "personality" in body:
        updates["personality"] = int(body["personality"])
    if "level" in body:
        species = updates["species"]
        level = int(body["level"])
        growth_rate = growth_rate_for_species(species)
        if growth_rate is not None:
            updates["experience"] = experience_for_level(growth_rate, level)
    location = str(body.get("location", "party"))
    if location == "box":
        box = int(body["box"])
        box_slot = int(body["box_slot"])
        before = next((pokemon for pokemon in save.boxes() if pokemon.box == box and pokemon.box_slot == box_slot), None)
        pokemon = save.update_box_pokemon(box, box_slot, updates)
        STATE.dirty = True
        message = f"已写入盒子 {box}-{box_slot}：{format_species(pokemon.species)}"
        record_change(message, pokemon_diffs(before, pokemon))
        return {"ok": True, "message": message}
    slot = int(body["slot"])
    updates["level"] = int(body["level"])
    party = save.party()
    before = party[slot - 1] if 1 <= slot <= len(party) else None
    pokemon = save.update_party_pokemon(slot, updates)
    STATE.dirty = True
    message = f"已写入队伍 {slot}：{format_species(pokemon.species)}"
    record_change(message, pokemon_diffs(before, pokemon))
    return {"ok": True, "message": message}


def pokemon_diffs(before, after) -> list[dict]:
    if before is None:
        return []
    fields = [
        ("种族", format_species(before.species), format_species(after.species)),
        ("携带", format_item(before.held_item) if before.held_item else "空", format_item(after.held_item) if after.held_item else "空"),
        ("等级", before.level, after.level),
        ("亲密度", before.friendship, after.friendship),
        ("性格", before.nature_name, after.nature_name),
        ("性别", before.gender, after.gender),
        ("闪光", "是" if before.is_shiny else "否", "是" if after.is_shiny else "否"),
        ("球", before.caught_ball_name, after.caught_ball_name),
        ("特性位", before.ability_bit, after.ability_bit),
        ("蛋", "是" if before.is_egg else "否", "是" if after.is_egg else "否"),
        ("招式", " / ".join(format_move(move_id) if move_id else "空" for move_id in before.moves), " / ".join(format_move(move_id) if move_id else "空" for move_id in after.moves)),
        ("PP", ",".join(map(str, before.pps)), ",".join(map(str, after.pps))),
        ("个体值", ",".join(map(str, before.ivs)), ",".join(map(str, after.ivs))),
        ("努力值", ",".join(map(str, before.evs)), ",".join(map(str, after.evs))),
    ]
    return [{"field": field, "before": old, "after": new} for field, old, new in fields if old != new]


def api_save():
    save = require_save()
    backup = save.save()
    load_save(save.path)
    return {"ok": True, "message": f"已保存，备份：{backup.name}"}


def api_close():
    STATE.save_path = None
    STATE.save = None
    STATE.rom_path = None
    STATE.dirty = False
    STATE.changes = []
    STATE.error = "请选择存档文件"
    configure_rom(None)
    return api_state()


def require_save() -> EmeraldSave:
    if not STATE.save:
        raise ValueError("存档未加载")
    return STATE.save


def parse_list(value, expected: int) -> list[int]:
    if isinstance(value, list):
        values = value
    else:
        values = [part.strip() for part in str(value).replace("，", ",").split(",") if part.strip()]
    if len(values) != expected:
        raise ValueError(f"需要 {expected} 个数字")
    return [int(v) for v in values]


def parse_id(value) -> int:
    text = str(value).strip()
    if text.startswith("#"):
        text = text[1:]
    return int(text.split()[0])


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>漆黑的魅影信息采集器</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", Arial, sans-serif; color: #1d211f; background: #f5f6f2; }
    header { min-height: 58px; display: flex; gap: 12px; align-items: center; padding: 9px 12px; background: #fbfbf8; border-bottom: 1px solid #d7d9d2; }
    input, select, button, textarea { font: inherit; }
    input, textarea, select { background: #fff; color: #1d211f; border: 1px solid #aeb5aa; border-radius: 6px; padding: 6px 7px; }
    button { border: 1px solid #9ba59a; border-radius: 6px; background: #fff; color: #1d211f; padding: 6px 10px; cursor: pointer; }
    button:hover:not(:disabled) { border-color: #35694f; background: #f4faf6; }
    button:disabled { color: #8a8f88; background: #eeeeeb; border-color: #d1d4ce; cursor: default; }
    button.primary { background: #2f6f4f; color: white; border-color: #265d42; }
    button.primary:hover:not(:disabled) { background: #285f43; border-color: #204d37; }
    button.primary:disabled { color: #8a8f88; background: #eeeeeb; border-color: #d1d4ce; }
    button.link { border: 0; background: transparent; color: #1f6f9f; padding: 0; text-align: left; text-decoration: underline; }
    .app-title { flex: 0 0 auto; font-weight: 700; letter-spacing: 0; }
    .file-state { flex: 1 1 auto; min-width: 0; display: grid; gap: 2px; }
    .file-line { display: flex; align-items: center; gap: 8px; min-width: 0; }
    .file-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
    .file-meta { min-width: 0; color: #626a61; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .toolbar { flex: 0 0 auto; display: flex; gap: 6px; align-items: center; }
    .pill { display: inline-flex; align-items: center; min-height: 20px; border: 1px solid #bec5bb; border-radius: 999px; padding: 1px 7px; font-size: 12px; font-weight: 500; background: #fff; color: #4d554b; white-space: nowrap; }
    .pill.clickable { cursor: pointer; }
    .pill.clickable:hover { border-color: #35694f; background: #f4faf6; }
    .pill.dirty { color: #8a4a00; border-color: #dfb66c; background: #fff7e6; }
    .pill.ok { color: #2f6f4f; border-color: #9fceb1; background: #eef8f1; }
    .pill.warn { color: #9f351f; border-color: #e6aa9e; background: #fff1ee; }
    main { display: grid; grid-template-columns: minmax(0, 1fr) 430px; gap: 10px; padding: 10px; height: calc(100vh - 58px); }
    .panel { background: #fff; border: 1px solid #d3d7cf; border-radius: 8px; min-height: 0; overflow: hidden; }
    section.panel { display: flex; flex-direction: column; }
    .tabs { display: flex; gap: 5px; padding: 7px; background: #f0f2ec; border-bottom: 1px solid #d7d9d2; flex-wrap: wrap; }
    .tabs button { padding: 6px 10px; }
    .tabs button.active { background: #24352d; border-color: #24352d; color: white; }
    .subtabs { background: #fff; }
    .dictionary-tabs { align-items: center; position: sticky; top: 0; z-index: 4; }
    .dictionary-tabs input { margin-left: auto; width: min(300px, 100%); }
    .summary { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 10px; border-bottom: 1px solid #e0e3dc; font-weight: 600; background: #fbfbf8; }
    .summary:empty { display: none; }
    .summary-controls { display: flex; align-items: center; gap: 6px; font-weight: 400; font-size: 13px; }
    .summary-controls select { padding: 4px 6px; }
    .metrics { display: grid; grid-template-columns: repeat(4, minmax(110px, 1fr)); gap: 6px; padding: 6px; border-bottom: 1px solid #ddd; background: #fafafa; }
    .metric { border: 1px solid #d0d0d0; background: white; padding: 5px 6px; border-radius: 6px; }
    .metric.clickable { cursor: pointer; }
    .metric.clickable:hover { border-color: #0969da; background: #f0f6ff; }
    .metric b { display: block; font-size: 16px; margin-bottom: 1px; }
    .filters { display: flex; gap: 6px; align-items: center; padding: 6px; border-bottom: 1px solid #ddd; background: #f7f7f7; flex-wrap: wrap; }
    .filters input { width: min(220px, 100%); }
    .badge { display: inline-block; border: 1px solid #aeb5aa; border-radius: 999px; padding: 1px 7px; font-size: 12px; background: #fff; color: #4d554b; }
    .empty-state { padding: 18px; color: #5d655c; }
    .id-chip { display: inline-block; font-variant-numeric: tabular-nums; color: #555; margin-right: 3px; }
    .muted { color: #6a7168; }
    .num { font-variant-numeric: tabular-nums; }
    .shiny-badge { color: #9a6700; font-weight: 700; }
    .bad { color: #b42318; font-weight: 600; }
    .table-wrap { overflow: auto; flex: 1 1 auto; min-height: 0; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: auto; }
    th, td { border-bottom: 1px solid #eceee8; padding: 5px 7px; text-align: left; white-space: normal; vertical-align: top; }
    td input { width: 100%; min-width: 96px; }
    td:nth-child(1), td:nth-child(2), td:nth-child(8) { white-space: nowrap; }
    td:nth-child(3), td:nth-child(4), td:nth-child(5), td:nth-child(6) { max-width: 260px; overflow-wrap: anywhere; }
    th { position: sticky; top: 0; background: #e8ece5; z-index: 1; }
    tr:hover { background: #f1f7f4; }
    tr.selected { background: #dcefe4; }
    aside { padding: 10px; overflow: auto; display: flex; flex-direction: column; gap: 8px; }
    aside label { display: block; margin-top: 8px; font-size: 13px; color: #333; }
    aside input, aside select, aside textarea { width: 100%; margin-top: 3px; }
    .form-grid { display: grid; gap: 6px; align-items: end; margin-top: 8px; }
    .form-grid label { margin-top: 0; min-width: 0; }
    .form-grid input, .form-grid select { min-width: 0; }
    .form-grid-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .pid-grid { grid-template-columns: minmax(0, 1fr) 68px; }
    .toggle-field { display: flex; flex-direction: column; justify-content: flex-end; }
    .toggle-field input { display: none; }
    .hint-mark { position: relative; display: inline-block; margin-left: 4px; color: #666; cursor: help; font-weight: 700; }
    .hint-mark:hover::after { content: attr(data-tip); position: absolute; left: 0; top: 18px; z-index: 20; width: 210px; padding: 6px 7px; border: 1px solid #999; background: #111; color: white; border-radius: 4px; font-weight: 400; line-height: 1.35; white-space: normal; box-shadow: 0 2px 8px rgba(0,0,0,.18); }
    .inspector-head { border-bottom: 1px solid #e0e3dc; padding-bottom: 8px; }
    #inspector-title { font-weight: 700; line-height: 1.35; overflow-wrap: anywhere; }
    #detail { max-height: 150px; white-space: pre-wrap; overflow: auto; background: #f8f9f5; border: 1px solid #d9ded6; border-radius: 6px; padding: 8px; color: #394038; }
    #detail:empty { display: none; }
    #detail.structured { max-height: none; white-space: normal; background: transparent; border: 0; padding: 0; }
    .detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; }
    .detail-field { border: 1px solid #d9ded6; border-radius: 6px; padding: 7px; background: #f8f9f5; min-width: 0; }
    .detail-field.wide { grid-column: 1 / -1; }
    .detail-label { display: block; color: #626a61; font-size: 12px; margin-bottom: 3px; }
    .detail-value { overflow-wrap: anywhere; }
    .chip-list { display: flex; flex-wrap: wrap; gap: 4px; }
    .data-chip { display: inline-flex; align-items: center; min-height: 20px; border: 1px solid #cbd1c7; border-radius: 999px; padding: 1px 7px; background: #fff; color: #30372f; font-size: 12px; }
    .type-chip { border-color: #aeb5aa; background: #edf4ef; color: #24352d; font-weight: 600; }
    .pokemon-type-row { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
    .type-badge { display: inline-flex; min-width: 42px; justify-content: center; align-items: center; min-height: 18px; border-radius: 3px; border: 1px solid rgba(0,0,0,.22); padding: 1px 6px; color: white; font-size: 12px; font-weight: 700; text-shadow: 0 1px 0 rgba(0,0,0,.35); box-shadow: inset 0 1px 0 rgba(255,255,255,.25); }
    .encounter-panel { margin-top: 8px; }
    .encounter-list { display: grid; gap: 4px; margin-top: 4px; }
    button.location-link { border-color: #a9c7d8; color: #1f5f85; background: #f2f9fc; text-decoration: none; }
    button.location-link:hover { border-color: #1f6f9f; background: #e5f4fb; }
    .dictionary-table td { vertical-align: middle; }
    .dictionary-table .name-cell { min-width: 130px; }
    .dictionary-species .types-cell { min-width: 104px; }
    .dictionary-species .types-cell .pokemon-type-row { flex-wrap: nowrap; margin-top: 0; }
    .dictionary-table .code-cell { max-width: 170px; color: #555; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
    .dictionary-table .description-cell { min-width: 180px; max-width: 360px; }
    .base-stat-grid { display: grid; grid-template-columns: repeat(6, minmax(28px, 1fr)); gap: 4px; min-width: 190px; }
    .base-stat { display: grid; gap: 1px; text-align: center; }
    .base-stat-label { color: #626a61; font-size: 11px; line-height: 1.1; }
    .base-stat-value { font-variant-numeric: tabular-nums; font-weight: 700; line-height: 1.2; }
    .type-chart-wrap { overflow: auto; padding: 8px; }
    .type-chart { min-width: 900px; table-layout: fixed; }
    .type-chart th, .type-chart td { text-align: center; white-space: nowrap; padding: 4px; }
    .type-chart th:first-child { left: 0; z-index: 2; }
    .effect-0 { background: #eceff1; color: #5f666c; }
    .effect-025, .effect-05 { background: #f7e8e4; color: #9f351f; font-weight: 600; }
    .effect-1 { background: #fbfcf8; color: #6a7168; }
    .effect-2, .effect-4 { background: #e4f2e8; color: #236341; font-weight: 700; }
    .type-tools { display: flex; align-items: center; gap: 8px; padding: 8px; border-bottom: 1px solid #e0e3dc; flex-wrap: wrap; }
    .type-tools label { display: flex; align-items: center; gap: 4px; }
    .type-profile { display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 7px; padding: 8px; border-bottom: 1px solid #e0e3dc; }
    .type-profile h4 { margin: 0 0 4px; font-size: 13px; }
    #status { color: #4d554b; white-space: pre-wrap; font-size: 13px; }
    .move-grid { display: grid; grid-template-columns: minmax(0, 1fr) 132px; gap: 6px; align-items: end; margin-top: 8px; }
    .move-grid label { margin-top: 0; }
    .move-grid select, .move-grid input { width: 100%; }
    .move-grid select { min-width: 0; }
    .pokemon-table th.sprite-col, .pokemon-table td.sprite-col { width: 42px; min-width: 42px; padding: 3px; text-align: center; }
    .pokemon-sprite { width: 32px; height: 32px; border: 1px solid #cfcfcf; background: #f3f3f3; image-rendering: pixelated; image-rendering: crisp-edges; }
    .pokemon-form-top { display: flex; gap: 8px; align-items: stretch; }
    .pokemon-form-left { flex: 0 0 calc((100% - 6px) / 2); width: calc((100% - 6px) / 2); min-width: 0; max-width: calc((100% - 6px) / 2); }
    .pokemon-form-sprite-wrap { flex: none; align-self: stretch; aspect-ratio: 1 / 1; border: 1px solid #bfbfbf; background: #f3f3f3; display: flex; align-items: center; justify-content: center; }
    .pokemon-form-sprite { width: 100%; height: 100%; image-rendering: pixelated; image-rendering: crisp-edges; }
    .pokemon-layout { display: grid; grid-template-rows: auto minmax(0, 1fr); height: 100%; min-height: 0; overflow: hidden; }
    .pokemon-map { display: grid; grid-template-columns: repeat(auto-fill, minmax(154px, 1fr)); grid-auto-rows: minmax(118px, auto); align-content: start; gap: 8px; max-height: min(360px, 45vh); overflow: auto; padding: 8px; border-bottom: 1px solid #e0e3dc; background: #fbfbf8; }
    .pokemon-list { min-height: 0; overflow: auto; }
    .list-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 10px; border-bottom: 1px solid #e0e3dc; background: #fff; font-weight: 600; }
    .box-overview { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 8px; padding: 8px; }
    .box-card { border: 1px solid #d3d7cf; border-radius: 6px; background: #fbfbf8; padding: 7px; cursor: pointer; }
    .box-card:hover { border-color: #35694f; background: #f4faf6; }
    .box-card.active { border-color: #2f6f4f; background: #edf8f1; box-shadow: inset 0 0 0 1px #2f6f4f; }
    .storage-card { min-width: 0; }
    .party-storage { grid-row: span 2; }
    .box-card h3 { margin: 0 0 6px; font-size: 13px; display: flex; justify-content: space-between; gap: 6px; }
    .box-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 3px; }
    .party-grid { display: grid; grid-template-columns: 1fr; grid-template-rows: repeat(6, minmax(28px, 1fr)); gap: 5px; height: calc(100% - 24px); }
    .box-grid.active { padding: 8px; border-bottom: 1px solid #e0e3dc; background: #fbfbf8; }
    .box-slot { aspect-ratio: 1 / 1; min-width: 0; border: 1px solid #d9ded6; border-radius: 4px; background: #eef1ea; display: flex; align-items: center; justify-content: center; position: relative; }
    .party-grid .box-slot { aspect-ratio: auto; }
    .party-slot { min-height: 30px; }
    .box-slot.occupied { background: #fff; cursor: pointer; }
    .box-slot.occupied:hover { border-color: #1f6f9f; background: #eef8ff; }
    .box-slot.occupied:hover::after { content: attr(data-name); position: absolute; left: 50%; bottom: calc(100% + 5px); transform: translateX(-50%); z-index: 12; min-width: max-content; max-width: 180px; padding: 4px 6px; border-radius: 4px; background: #1f2722; color: white; font-size: 12px; line-height: 1.3; white-space: nowrap; box-shadow: 0 2px 8px rgba(0,0,0,.2); pointer-events: none; }
    .box-slot.selected { border-color: #2f6f4f; box-shadow: inset 0 0 0 1px #2f6f4f; }
    .box-slot-index { position: absolute; left: 3px; top: 2px; font-size: 10px; color: #7b8279; }
    .box-mini-sprite { width: 100%; height: 100%; max-width: 32px; max-height: 32px; image-rendering: pixelated; image-rendering: crisp-edges; }
    .single-toggle { width: 100%; height: 31px; margin-top: 3px; border: 0; background: transparent; color: #111; padding: 0; display: flex; align-items: center; justify-content: center; }
    .single-toggle .track { width: 42px; height: 22px; border-radius: 999px; background: #d0d0d0; position: relative; flex: 0 0 auto; }
    .single-toggle .thumb { width: 18px; height: 18px; border-radius: 999px; background: #fff; border: 1px solid #888; position: absolute; left: 2px; top: 2px; transition: left .12s ease; }
    .single-toggle.active .track { background: #3b82f6; }
    .single-toggle.active .thumb { left: 22px; border-color: #2a63b7; }
    .trait-row { display: grid; grid-template-columns: calc((100% - 12px) / 2) minmax(0, 1fr) minmax(0, 1fr); gap: 6px; align-items: end; margin-top: 8px; }
    .status-row { display: grid; grid-template-columns: calc((100% - 12px) / 2) minmax(0, 1fr) minmax(0, 1fr); gap: 6px; align-items: end; margin-top: 8px; }
    .status-pack { display: grid; grid-template-columns: 56px minmax(0, 1fr); gap: 4px; align-items: end; }
    .stats-row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; align-items: end; margin-top: 8px; }
    .trait-row label, .status-row label, .status-pack label, .stats-row label { margin-top: 0; min-width: 0; }
    .trait-row input, .trait-row select, .trait-row button,
    .status-row input, .status-row select, .status-row button,
    .status-pack input, .status-pack select, .status-pack button,
    .stats-row input, .stats-row select, .stats-row button { width: 100%; min-width: 0; }
    .pp-up-control { display: grid; grid-template-columns: repeat(4, 1fr); gap: 2px; margin-top: 3px; }
    .pp-up-control button { padding: 5px 0; min-width: 0; }
    .pp-up-control button.active { background: #111; color: white; }
    select.invalid-move { border-color: #b42318; background: #fff1f0; color: #7a1d15; }
    @media (max-width: 1100px) {
      header { align-items: flex-start; flex-wrap: wrap; }
      .toolbar { width: 100%; }
      .toolbar button { flex: 1 1 0; }
      main { grid-template-columns: 1fr; height: auto; min-height: calc(100vh - 58px); }
      aside { min-height: 170px; }
      .dictionary-tabs input { margin-left: 0; width: 100%; }
      .metrics { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
    }
  </style>
</head>
<body>
  <datalist id="species-list"></datalist>
  <datalist id="item-list"></datalist>
  <datalist id="move-list"></datalist>
  <header>
    <div class="app-title">漆黑的魅影存档编辑器</div>
    <div class="file-state" id="file-state">
      <div class="file-line">
        <span class="file-name" id="file-name">未加载存档</span>
        <span class="pill" id="dirty-pill">未修改</span>
        <span class="pill" id="rom-pill">ROM 未加载</span>
      </div>
      <div class="file-meta" id="file-meta">请选择 .sav 文件</div>
    </div>
    <div class="toolbar">
      <button id="open-btn" onclick="openSave()">打开</button>
      <button id="reload-btn" onclick="reloadSave()" disabled>重载</button>
      <button id="save-btn" class="primary" onclick="saveFile()" disabled>保存</button>
      <button id="close-btn" onclick="closeSave()" disabled>关闭</button>
    </div>
  </header>
  <main>
    <section class="panel">
      <div class="tabs">
        <button id="tab-overview" onclick="showTab('overview')" disabled>存档概览</button>
        <button id="tab-pokemon" onclick="showTab('pokemon')" disabled>宝可梦</button>
        <button id="tab-bag" onclick="showTab('bag')" disabled>背包</button>
        <button id="tab-names" onclick="showTab('names')" disabled>字典表</button>
      </div>
      <div class="summary" id="summary">加载中</div>
      <div class="table-wrap" id="content"></div>
    </section>
    <aside class="panel">
      <div class="inspector-head">
        <div id="inspector-title">未选择条目</div>
      </div>
      <div id="detail"></div>
      <form id="form"></form>
      <div id="status"></div>
    </aside>
  </main>
<script>
let state = null;
let names = null;
let tab = "overview";
let selected = null;
let bagSort = "slot";
let bagPocket = "all";
let pokemonView = "party";
let collectTable = "species";
let collectSearch = "";
let collectCodeFilter = [];
let collectCodeLabel = "";
let pokemonFormConstraints = null;
let typeDefenseA = 10;
let typeDefenseB = 11;
const TYPE_NAMES = ["一般", "格斗", "飞行", "毒", "地面", "岩石", "虫", "幽灵", "钢", "未知09", "火", "水", "草", "电", "超能", "冰", "龙", "恶"];
const TYPE_CHART_IDS = TYPE_NAMES.map((_name, id) => id).filter(id => id !== 9);
const TYPE_COLORS = {
  "一般": "#9fa19f", "格斗": "#ff8000", "飞行": "#81b9ef", "毒": "#9141cb", "地面": "#915121", "岩石": "#afa981",
  "虫": "#91a119", "幽灵": "#704170", "钢": "#60a1b8", "未知09": "#68a090", "火": "#e62829", "水": "#2980ef",
  "草": "#3fa129", "电": "#fac000", "超能": "#ef4179", "冰": "#3fd8ff", "龙": "#5060e1", "恶": "#50413f",
};
const TYPE_EFFECTIVENESS = {
  "0>5": 0.5, "0>7": 0, "0>8": 0.5,
  "1>0": 2, "1>2": 0.5, "1>3": 0.5, "1>5": 2, "1>6": 0.5, "1>7": 0, "1>8": 2, "1>14": 0.5, "1>15": 2, "1>17": 2,
  "2>1": 2, "2>5": 0.5, "2>6": 2, "2>8": 0.5, "2>12": 2, "2>13": 0.5,
  "3>3": 0.5, "3>4": 0.5, "3>5": 0.5, "3>7": 0.5, "3>8": 0, "3>12": 2,
  "4>2": 0, "4>3": 2, "4>5": 2, "4>6": 0.5, "4>8": 2, "4>10": 2, "4>12": 0.5, "4>13": 2,
  "5>1": 0.5, "5>2": 2, "5>4": 0.5, "5>6": 2, "5>8": 0.5, "5>10": 2, "5>15": 2,
  "6>1": 0.5, "6>2": 0.5, "6>3": 0.5, "6>7": 0.5, "6>8": 0.5, "6>10": 0.5, "6>12": 2, "6>14": 2, "6>17": 2,
  "7>0": 0, "7>7": 2, "7>8": 0.5, "7>14": 2, "7>17": 0.5,
  "8>5": 2, "8>8": 0.5, "8>10": 0.5, "8>11": 0.5, "8>13": 0.5, "8>15": 2,
  "10>5": 0.5, "10>6": 2, "10>8": 2, "10>10": 0.5, "10>11": 0.5, "10>12": 2, "10>15": 2, "10>16": 0.5,
  "11>4": 2, "11>5": 2, "11>10": 2, "11>11": 0.5, "11>12": 0.5, "11>16": 0.5,
  "12>2": 0.5, "12>3": 0.5, "12>4": 2, "12>5": 2, "12>6": 0.5, "12>8": 0.5, "12>10": 0.5, "12>11": 2, "12>12": 0.5, "12>16": 0.5,
  "13>2": 2, "13>4": 0, "13>11": 2, "13>12": 0.5, "13>13": 0.5, "13>16": 0.5,
  "14>1": 2, "14>3": 2, "14>8": 0.5, "14>14": 0.5, "14>17": 0,
  "15>2": 2, "15>4": 2, "15>8": 0.5, "15>10": 0.5, "15>11": 0.5, "15>12": 2, "15>15": 0.5, "15>16": 2,
  "16>8": 0.5, "16>16": 2,
  "17>1": 0.5, "17>7": 2, "17>8": 0.5, "17>14": 2, "17>17": 0.5,
};

async function request(url, options, allowFalse=false) {
  const res = await fetch(url, options);
  const data = await res.json();
  if (!res.ok || (!allowFalse && data.ok === false)) throw new Error(data.error || data.message || "请求失败");
  return data;
}
async function refresh() {
  [state, names] = await Promise.all([request("/api/state", undefined, true), request("/api/names")]);
  render();
}
async function openSave() {
  if (!confirmDiscard("打开其他存档")) return;
  try {
    state = await request("/api/pick_save");
    names = await request("/api/names");
    selected = null;
    render();
  } catch (err) {
    await refresh();
    setStatus(err.message);
  }
}
async function reloadSave() {
  if (!state?.path) return;
  if (!confirmDiscard("重载存档")) return;
  try {
    state = await request("/api/load");
    names = await request("/api/names");
    selected = null;
    render();
  } catch (err) {
    await refresh();
    setStatus(err.message);
  }
}
async function saveFile() {
  if (!state?.ok || !state?.dirty) return;
  try {
    const data = await request("/api/save", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"});
    await refresh();
    setStatus(data.message);
  } catch (err) {
    setStatus(err.message);
  }
}
async function closeSave() {
  if (!state?.ok) return;
  if (!confirmDiscard("关闭存档")) return;
  try {
    state = await request("/api/close", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"}, true);
    names = await request("/api/names");
    selected = null;
    tab = "overview";
    render();
  } catch (err) {
    setStatus(err.message);
  }
}
function showTab(next) { tab = next; selected = null; render(); }
function setStatus(text) { document.getElementById("status").textContent = text; }
function confirmDiscard(action) {
  if (!state?.dirty) return true;
  return window.confirm(`当前修改还没有保存，${action} 会丢弃这些修改。继续？`);
}
function render() {
  renderDatalists();
  renderShell();
  for (const id of ["overview","pokemon","bag","names"]) document.getElementById("tab-"+id).classList.toggle("active", tab === id);
  document.getElementById("form").innerHTML = "";
  setInspector("未选择条目");
  if (!state || !state.ok) {
    document.getElementById("summary").textContent = "";
    document.getElementById("content").innerHTML = `<div class="empty-state">${escapeHtml(state?.error || "请选择存档文件")}</div>`;
    setInspector("未加载存档", state?.error || "");
    return;
  }
  if (tab === "overview") renderOverview();
  if (tab === "bag") renderBag();
  if (tab === "pokemon") renderPokemonPage();
  if (tab === "names") renderNames();
}
function renderShell() {
  const loaded = Boolean(state?.ok);
  const dirty = Boolean(state?.dirty);
  const romLoaded = Boolean(state?.rom_path);
  const fileName = document.getElementById("file-name");
  const fileMeta = document.getElementById("file-meta");
  const dirtyPill = document.getElementById("dirty-pill");
  const romPill = document.getElementById("rom-pill");
  const changeCount = (state?.changes || []).length;
  fileName.textContent = loaded ? basename(state.path) : "未加载存档";
  fileName.title = state?.path || "";
  fileMeta.textContent = loaded ? `${state.path}${state.rom_path ? " · ROM " + basename(state.rom_path) : " · 未找到同名 ROM"}` : (state?.error || "请选择 .sav 文件");
  fileMeta.title = loaded ? `${state.path}${state.rom_path ? "\n" + state.rom_path : ""}` : "";
  dirtyPill.textContent = loaded ? (dirty ? `未保存 ${changeCount}` : "已保存") : "未加载";
  dirtyPill.title = dirty ? "点击查看未保存修改" : "";
  dirtyPill.onclick = dirty ? showPendingChanges : null;
  dirtyPill.className = "pill" + (dirty ? " dirty clickable" : loaded ? " ok" : "");
  romPill.textContent = loaded ? (romLoaded ? "ROM 已加载" : "ROM 缺失") : "ROM 未加载";
  romPill.className = "pill" + (romLoaded ? " ok" : " warn");
  document.getElementById("reload-btn").disabled = !loaded;
  document.getElementById("save-btn").disabled = !loaded || !dirty;
  document.getElementById("close-btn").disabled = !loaded;
  for (const id of ["overview","pokemon","bag","names"]) document.getElementById("tab-"+id).disabled = !loaded;
}
function showPendingChanges() {
  const changes = state?.changes || [];
  if (!changes.length) {
    setInspector("未保存修改", "暂无记录");
    return;
  }
  document.getElementById("form").innerHTML = "";
  setInspectorHtml("未保存修改", `<div class="detail-grid">${changes.map(renderPendingChange).join("")}</div>`);
}
function renderPendingChange(change, index) {
  const summary = typeof change === "string" ? change : change.summary;
  const diffs = typeof change === "string" ? [] : (change.diffs || []);
  const diffRows = diffs.length ? `<table><thead><tr><th>字段</th><th>原值</th><th>新值</th></tr></thead><tbody>${diffs.map(diff => `<tr><td>${escapeHtml(diff.field)}</td><td>${escapeHtml(diff.before)}</td><td>${escapeHtml(diff.after)}</td></tr>`).join("")}</tbody></table>` : `<div class="muted">没有字段差异</div>`;
  return `<div class="detail-field wide"><span class="detail-label">#${index + 1}</span><div class="detail-value">${escapeHtml(summary)}</div>${diffRows}</div>`;
}
function basename(path) {
  return String(path || "").split(/[\\/]/).filter(Boolean).pop() || "";
}
function setInspector(title, detail="") {
  document.getElementById("inspector-title").textContent = title || "未选择条目";
  const detailNode = document.getElementById("detail");
  detailNode.classList.remove("structured");
  detailNode.textContent = detail || "";
}
function setInspectorHtml(title, detailHtml="") {
  document.getElementById("inspector-title").textContent = title || "未选择条目";
  const detailNode = document.getElementById("detail");
  detailNode.classList.add("structured");
  detailNode.innerHTML = detailHtml || "";
}
function renderDatalists() {
  if (!names) return;
  document.getElementById("species-list").innerHTML = names.species.map(e => `<option value="${idName(e.id, e.name)}"></option>`).join("");
  document.getElementById("item-list").innerHTML = names.items.map(e => `<option value="${idName(e.id, e.name)}"></option>`).join("");
  document.getElementById("move-list").innerHTML = names.moves.map(e => `<option value="${e.id}" label="${escapeHtml(e.name)}"></option>`).join("");
}
function idName(id, name) {
  return `#${id} · ${escapeHtml(name || "")}`.trim();
}
function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function escapeJsString(text) {
  return String(text).replace(/\\/g, "\\\\").replace(/'/g, "\\'").replace(/\n/g, "\\n").replace(/\r/g, "");
}
function romLink(table, id, text) {
  if (!id) return escapeHtml(text || "空");
  return `<button type="button" class="link" onclick="jumpToRom('${table}', ${id}); event.stopPropagation();">${escapeHtml(text)}</button>`;
}
function displayName(table, id, text) {
  return `<span class="id-chip">#${id}</span> ${romLink(table, id, text)}`;
}
function renderSubtabs(items, current, onclickName) {
  return `<div class="tabs subtabs">${items.map(([id, label]) => `<button class="${current===id?"active":""}" onclick="${onclickName}('${escapeJsString(id)}')">${escapeHtml(label)}</button>`).join("")}</div>`;
}
function renderOverview() {
  const t = state.trainer || {};
  const inv = state.inventory || {};
  const play = t.play_time || {};
  document.getElementById("summary").textContent = `存档概览：当前槽 ${state.active}，安全钥 ${state.security_key}`;
  const bagStats = Object.entries(state.bag_by_pocket || {}).map(([name, s]) => `<tr><td>${escapeHtml(name)}</td><td>${s.filled}/${s.total}</td></tr>`).join("");
  const boxStats = Array.from({length: 14}, (_, i) => {
    const box = String(i + 1);
    const s = (state.boxes_by_box || {})[box] || {filled: 0, total: 30};
    return `<tr><td>盒子 ${box}</td><td>${s.filled}/${s.total}</td></tr>`;
  }).join("");
  const sections = (state.sections || []).map(row => `<tr><td>${row.slot}${row.active ? " 当前" : ""}</td><td>${row.section_id}</td><td>${row.ok ? "OK" : "错误"}</td><td>${row.physical_index ?? ""}</td><td>${row.save_index ?? ""}</td><td>${row.checksum || ""}</td><td>${row.calculated || ""}</td></tr>`).join("");
  document.getElementById("content").innerHTML = `
    <div class="metrics">
      <div class="metric"><b>${escapeHtml(t.gender || "")}</b>训练家性别</div>
      <div class="metric"><b>${t.trainer_id ?? ""}</b>训练家 ID</div>
      <div class="metric"><b>${t.secret_id ?? ""}</b>隐藏 ID</div>
      <div class="metric"><b>${inv.money ?? ""}</b>金钱</div>
      <div class="metric"><b>${inv.coins ?? ""}</b>游戏币</div>
      <div class="metric"><b>${play.hours ?? 0}:${String(play.minutes ?? 0).padStart(2, "0")}:${String(play.seconds ?? 0).padStart(2, "0")}</b>游戏时间</div>
      <div class="metric"><b>${state.party.length}</b>队伍宝可梦</div>
      <div class="metric"><b>${state.boxes.length}</b>盒子占用</div>
    </div>
    <table><thead><tr><th colspan="2">训练家原始字段</th></tr></thead><tbody>
      <tr><td>名字原始字节</td><td>${escapeHtml(t.name_raw || "")}</td></tr>
      <tr><td>可打印字符</td><td>${escapeHtml(t.name_ascii || "")}</td></tr>
      <tr><td>性别原始值</td><td>${t.gender_value ?? ""}</td></tr>
    </tbody></table>
    <table><thead><tr><th>背包口袋</th><th>非空/总格</th></tr></thead><tbody>${bagStats}</tbody></table>
    <table><thead><tr><th>盒子</th><th>占用/总格</th></tr></thead><tbody>${boxStats}</tbody></table>
    <table><thead><tr><th>槽</th><th>Section</th><th>校验</th><th>物理序号</th><th>保存序号</th><th>存储校验</th><th>计算校验</th></tr></thead><tbody>${sections}</tbody></table>`;
  setInspector("存档概览");
}
function renderBag() {
  const nonempty = state.bag.filter(e => e.item_id || e.quantity).length;
  const pockets = [["all", "全部"], ...Object.keys(state.bag_by_pocket || {}).map(name => [name, `${name} ${(state.bag_by_pocket[name] || {}).filled || 0}/${(state.bag_by_pocket[name] || {}).total || 0}`])];
  document.getElementById("summary").innerHTML = `
    <span>背包：${nonempty} 个非空格 / ${state.bag.length} 个总格位，当前槽 ${state.active}</span>
    <span class="summary-controls">
      <label>排序
        <select onchange="setBagSort(this.value)">
          <option value="slot" ${bagSort==="slot"?"selected":""}>原始顺序</option>
          <option value="slot_desc" ${bagSort==="slot_desc"?"selected":""}>原始逆序</option>
          <option value="filled" ${bagSort==="filled"?"selected":""}>已有内容优先</option>
          <option value="filled_desc" ${bagSort==="filled_desc"?"selected":""}>已有内容逆序</option>
          <option value="item_id" ${bagSort==="item_id"?"selected":""}>道具 ID 顺序</option>
          <option value="item_id_desc" ${bagSort==="item_id_desc"?"selected":""}>道具 ID 逆序</option>
        </select>
      </label>
    </span>`;
  const rows = sortedBagRows().filter(({e}) => bagPocket === "all" || e.pocket === bagPocket);
  let html = "<table><thead><tr><th>口袋</th><th>格位</th><th>道具 ID</th><th>名称</th><th>数量</th></tr></thead><tbody>";
  rows.forEach(({e, i}) => html += `<tr id="save-bag-${i}" class="${selected===i?"selected":""}" onclick="selectBag(${i})"><td>${escapeHtml(e.pocket)}</td><td>${e.slot}</td><td>${e.item_id}</td><td>${romLink("items", e.item_id, e.name)}</td><td>${e.quantity}</td></tr>`);
  document.getElementById("content").innerHTML = renderSubtabs(pockets, bagPocket, "setBagPocket") + html + "</tbody></table>";
}
function setBagPocket(next) { bagPocket = next; selected = null; renderBag(); }
function setBagSort(next) {
  bagSort = next;
  renderBag();
}
function sortedBagRows() {
  const rows = state.bag.map((e, i) => ({e, i}));
  const filled = row => row.e.item_id || row.e.quantity ? 0 : 1;
  if (bagSort === "slot_desc") return rows.reverse();
  if (bagSort === "filled") return rows.sort((a, b) => filled(a) - filled(b) || a.i - b.i);
  if (bagSort === "filled_desc") return rows.sort((a, b) => filled(a) - filled(b) || b.i - a.i);
  if (bagSort === "item_id") return rows.sort((a, b) => a.e.item_id - b.e.item_id || a.i - b.i);
  if (bagSort === "item_id_desc") return rows.sort((a, b) => b.e.item_id - a.e.item_id || b.i - a.i);
  return rows;
}
function selectBag(i) {
  selected = i;
  const e = state.bag[i];
  setInspector(`${e.pocket} #${e.slot}`, `道具：${e.item_id} ${e.name}\n数量：${e.quantity}`);
  document.getElementById("form").innerHTML = `
    <label>口袋<select id="pocket">${["电脑道具","普通道具","重要道具","精灵球","招式机/秘传机","树果"].map(p=>`<option ${p===e.pocket?"selected":""}>${p}</option>`).join("")}</select></label>
    <label>格位<input id="slot" value="${e.slot}"></label>
    <label>道具 ID<input id="item_id" list="item-list" value="${e.item_id}"></label>
    <label>数量<input id="quantity" value="${e.quantity}"></label>
    <p><button type="button" class="primary" onclick="updateBag()">写入该格</button> <button type="button" onclick="clearBag()">清空该格</button></p>`;
}
async function updateBag() {
  const body = {pocket:val("pocket"), slot:num("slot"), item_id:num("item_id"), quantity:num("quantity")};
  const data = await request("/api/bag", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
  setStatus(data.message + "\n尚未保存到文件");
  await refresh();
}
function clearBag() { document.getElementById("item_id").value = 0; document.getElementById("quantity").value = 0; updateBag(); }
function renderPokemonPage() {
  if (pokemonView !== "party" && !/^\d+$/.test(String(pokemonView))) pokemonView = "party";
  const currentLabel = pokemonView === "party" ? "队伍" : `${pokemonView}号盒`;
  const boxStats = pokemonView === "party" ? null : ((state.boxes_by_box || {})[String(pokemonView)] || {filled: 0, total: 30});
  document.getElementById("summary").innerHTML = `
    <span>宝可梦：队伍 ${state.party.length}/6，盒子 ${state.boxes.length}/420</span>
    <span class="summary-controls">列表区：${escapeHtml(currentLabel)}${boxStats ? ` ${boxStats.filled}/${boxStats.total}` : ""}</span>`;
  document.getElementById("content").innerHTML = `
    <div class="pokemon-layout">
      <section class="pokemon-map" aria-label="盒子区">${renderPokemonStorageMap()}</section>
      <section class="pokemon-list" aria-label="列表区">${renderPokemonList()}</section>
    </div>`;
  renderSpritesIn(document.getElementById("content"));
}
function setPokemonView(next) {
  pokemonView = next;
  selected = null;
  renderPokemonPage();
}
function renderPokemonStorageMap() {
  return `
    <div class="box-card storage-card party-storage ${pokemonView==="party"?"active":""}" onclick="setPokemonView('party')">
      <h3><span>队伍</span><span>${state.party.length}/6</span></h3>
      ${renderPartyStorageGrid()}
    </div>
    ${Array.from({length: 14}, (_, index) => {
      const box = index + 1;
      const stats = (state.boxes_by_box || {})[String(box)] || {filled: 0, total: 30};
      return `<div class="box-card storage-card ${String(pokemonView)===String(box)?"active":""}" onclick="setPokemonView('${box}')"><h3><span>${box}号盒</span><span>${stats.filled}/${stats.total}</span></h3>${renderBoxGrid(box, false)}</div>`;
    }).join("")}`;
}
function renderPartyStorageGrid() {
  const slots = Array.from({length: 6}, (_, i) => i + 1).map(slot => {
    const pokemon = state.party.find(p => Number(p.slot) === slot);
    if (!pokemon) return `<div id="party-slot-${slot}" class="box-slot party-slot"><span class="box-slot-index">${slot}</span></div>`;
    const index = state.party.indexOf(pokemon);
    const label = `${pokemon.species_name} · 队伍 ${slot}`;
    return `<div id="party-slot-${slot}" class="box-slot party-slot occupied ${isPokemonSelected("party", index)?"selected":""}" title="${escapeHtml(label)}" data-name="${escapeHtml(label)}" onclick="selectPartyFromStorage(${index}); event.stopPropagation();"><span class="box-slot-index">${slot}</span>${spriteCanvasTag(`party-grid-${slot}`, pokemon.species, pokemon.is_shiny, "box-mini-sprite")}</div>`;
  }).join("");
  return `<div class="party-grid">${slots}</div>`;
}
function renderPokemonList() {
  const rows = pokemonView === "party"
    ? state.party.map((p, index) => ({kind: "party", p, index}))
    : state.boxes.filter(p => String(p.box) === String(pokemonView)).map(p => ({kind: "box", p, index: state.boxes.indexOf(p)}));
  const title = pokemonView === "party" ? "队伍列表" : `${pokemonView}号盒列表`;
  const empty = rows.length ? "" : `<tr><td colspan="12" class="muted">没有宝可梦</td></tr>`;
  const body = rows.map(({kind, p, index}) => pokemonTableRow(kind, p, index)).join("") || empty;
  return `
    <div class="list-title"><span>${escapeHtml(title)}</span><span>${rows.length} 只</span></div>
    <table class='pokemon-table'><thead><tr><th class='sprite-col'>图</th><th>位置</th><th>种族</th><th>属性</th><th>等级</th><th>性格</th><th>性别</th><th>特性</th><th>球</th><th>携带</th><th>招式</th><th>合法性</th></tr></thead><tbody>${body}</tbody></table>`;
}
function pokemonTableRow(kind, p, index) {
  const isParty = kind === "party";
  const moves = p.moves.map((id, idx) => romLink("moves", id, p.move_names[idx])).join(" / ");
  const held = p.held_item ? displayName("items", p.held_item, p.held_item_name) : "空";
  const id = isParty ? `save-party-${index}` : `save-box-${index}`;
  const location = isParty ? `队伍 ${p.slot}` : `盒子 ${p.box}-${p.box_slot}`;
  const level = isParty ? p.level : (p.level || "未知");
  const click = isParty ? `selectParty(${index})` : `selectBox(${index})`;
  return `<tr id="${id}" class="${isPokemonSelected(kind, index)?"selected":""}" onclick="${click}"><td class="sprite-col">${spriteCanvasTag(`${kind}-${index}`, p.species, p.is_shiny, "pokemon-sprite")}</td><td>${location}</td><td>${displayName("species", p.species, p.species_name)} ${shinyBadge(p)}</td><td>${pokemonTypeBadges(p.types)}</td><td>${level}</td><td>${p.nature_name}</td><td>${p.gender}</td><td>${displayName("abilities", p.ability_id, p.ability_name)}</td><td>${p.caught_ball_name}</td><td>${held}</td><td>${moves}</td><td>${legalityBadge(p)}</td></tr>`;
}
function isPokemonSelected(kind, index) {
  return selected && selected.kind === kind && selected.index === index;
}
function markPokemonSelection() {
  document.querySelectorAll(".box-slot.selected, .pokemon-table tr.selected").forEach(node => node.classList.remove("selected"));
  if (!selected) return;
  const rowId = selected.kind === "party" ? `save-party-${selected.index}` : `save-box-${selected.index}`;
  const row = document.getElementById(rowId);
  if (row) row.classList.add("selected");
  let slot = null;
  if (selected.kind === "party") {
    const pokemon = state.party[selected.index];
    if (pokemon) slot = document.getElementById(`party-slot-${pokemon.slot}`);
  } else {
    const pokemon = state.boxes[selected.index];
    if (pokemon) slot = document.getElementById(`box-slot-${pokemon.box}-${pokemon.box_slot}`);
  }
  if (slot) slot.classList.add("selected");
}
function pokemonFormMatches(location, pokemon) {
  const locationInput = document.getElementById("location");
  if (!locationInput || locationInput.value !== location) return false;
  if (location === "party") return Number(val("slot")) === Number(pokemon.slot);
  return Number(val("box")) === Number(pokemon.box) && Number(val("box_slot")) === Number(pokemon.box_slot);
}
function renderBoxGrid(box, active) {
  const slots = Array.from({length: 30}, (_, i) => i + 1).map(slot => {
    const pokemon = state.boxes.find(p => Number(p.box) === Number(box) && Number(p.box_slot) === slot);
    if (!pokemon) return `<div class="box-slot"><span class="box-slot-index">${slot}</span></div>`;
    const index = state.boxes.indexOf(pokemon);
    const click = ` onclick="selectBoxFromStorage(${index}); event.stopPropagation();"`;
    const label = `${pokemon.species_name} · ${box}-${slot}`;
    return `<div id="box-slot-${box}-${slot}" class="box-slot occupied ${isPokemonSelected("box", index)?"selected":""}" title="${escapeHtml(label)}" data-name="${escapeHtml(label)}"${click}><span class="box-slot-index">${slot}</span>${spriteCanvasTag(`box-grid-${box}-${slot}`, pokemon.species, pokemon.is_shiny, "box-mini-sprite")}</div>`;
  }).join("");
  return `<div class="box-grid ${active ? "active" : ""}">${slots}</div>`;
}
async function selectBoxFromGrid(index) {
  await selectBoxFromStorage(index);
}
async function selectPartyFromStorage(index) {
  pokemonView = "party";
  selected = {kind: "party", index};
  renderPokemonPage();
  await selectParty(index);
}
async function selectBoxFromStorage(index) {
  pokemonView = String(state.boxes[index].box);
  selected = {kind: "box", index};
  renderPokemonPage();
  await selectBox(index);
}
function legalityBadge(p) {
  const rows = p.legality || [];
  const ok = rows.length === 1 && /合法性通过$/.test(rows[0]);
  if (ok) return "通过";
  return `<span class="bad">可疑 ${rows.length}</span>`;
}
function shinyBadge(p) {
  return p.is_shiny ? `<span class="shiny-badge">闪</span>` : "";
}
function pokemonTypeBadges(types) {
  if (!types?.length) return `<span class="muted">未知</span>`;
  return `<span class="pokemon-type-row">${types.map(type => `<span class="type-badge" style="background:${TYPE_COLORS[type] || "#777"}">${escapeHtml(type)}</span>`).join("")}</span>`;
}
function speciesTypesForForm(speciesId, payloadTypes=[]) {
  if (payloadTypes?.length) return payloadTypes;
  return nameRow("species", speciesId)?.detail?.types || [];
}
function pokemonEncounterPanel(speciesId) {
  const row = nameRow("species", speciesId);
  const encounters = row?.detail?.encounters || [];
  if (!encounters.length) return `<div class="detail-field encounter-panel"><span class="detail-label">Encounter</span><div class="detail-value muted">无 Encounter 数据</div></div>`;
  return `<div class="detail-field encounter-panel"><span class="detail-label">Encounter</span><div class="encounter-list">${encounters.slice(0, 6).map(encounter => `<span>${escapeHtml(encounterLabel(encounter))} · 几率 ${escapeHtml(encounter.rate)} · 槽位 ${escapeHtml((encounter.slots || []).join("/"))}</span>`).join("")}${encounters.length > 6 ? `<span class="muted">+${encounters.length - 6}</span>` : ""}</div></div>`;
}
function refreshFormSpeciesMeta() {
  const typeTarget = document.getElementById("form-types");
  const encounterTarget = document.getElementById("form-encounters");
  const row = nameRow("species", idNum("species"));
  if (typeTarget) typeTarget.innerHTML = pokemonTypeBadges(row?.detail?.types || []);
  if (encounterTarget) encounterTarget.innerHTML = pokemonEncounterPanel(idNum("species"));
}
function spriteCanvasTag(id, species, shiny, className) {
  return `<canvas id="sprite-${escapeHtml(id)}" class="${className}" width="64" height="64" data-species="${Number(species) || 0}" data-shiny="${shiny ? 1 : 0}"></canvas>`;
}
function renderSpritesIn(root) {
  if (!root) return;
  root.querySelectorAll("canvas[data-species]").forEach(canvas => {
    void renderSpriteCanvas(canvas);
  });
}
async function renderSpriteCanvas(canvas) {
  const species = Number(canvas.dataset.species || 0);
  const shiny = Number(canvas.dataset.shiny || 0);
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  if (!species || species < 0) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }
  try {
    const data = await request(`/api/pokemon_sprite?species=${encodeURIComponent(species)}&shiny=${encodeURIComponent(shiny)}`);
    if (!data.available || !data.rgba_base64) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      return;
    }
    const raw = atob(data.rgba_base64);
    const rgba = new Uint8ClampedArray(raw.length);
    for (let i = 0; i < raw.length; i++) rgba[i] = raw.charCodeAt(i);
    const image = new ImageData(rgba, Number(data.width) || 64, Number(data.height) || 64);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.putImageData(image, 0, 0);
  } catch (_error) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }
}
function refreshFormSprite() {
  const canvas = document.getElementById("sprite-form");
  if (!canvas) return;
  syncPokemonFormTopSquare();
  canvas.dataset.species = String(idNum("species") || 0);
  canvas.dataset.shiny = String(Number(val("is_shiny") || 0));
  void renderSpriteCanvas(canvas);
}
function syncPokemonFormTopSquare() {
  const top = document.querySelector(".pokemon-form-top");
  if (!top) return;
  const left = top.querySelector(".pokemon-form-left");
  const spriteWrap = top.querySelector(".pokemon-form-sprite-wrap");
  if (!left || !spriteWrap) return;
  const size = Math.max(0, Math.round(left.getBoundingClientRect().height));
  if (!size) return;
  spriteWrap.style.width = `${size}px`;
  spriteWrap.style.height = `${size}px`;
  spriteWrap.style.minWidth = `${size}px`;
  spriteWrap.style.maxWidth = `${size}px`;
  spriteWrap.style.minHeight = `${size}px`;
  spriteWrap.style.maxHeight = `${size}px`;
}
async function selectParty(i) {
  const wasSelected = isPokemonSelected("party", i);
  selected = {kind: "party", index: i};
  markPokemonSelection();
  const p = state.party[i];
  setInspector(`${p.species_name} · 队伍 ${p.slot}`, p.legality.join("\n"));
  if (wasSelected && pokemonFormMatches("party", p)) return;
  pokemonFormConstraints = await loadPokemonConstraints(p.species, p.level);
  renderPokemonForm(p, pokemonFormConstraints, "party");
}
function renderPokemonForm(p, constraints, location) {
  const isBox = location === "box";
  document.getElementById("form").innerHTML = `
    <input type="hidden" id="location" value="${location}">
    ${isBox ? `<input type="hidden" id="box" value="${p.box}"><input type="hidden" id="box_slot" value="${p.box_slot}">` : `<input type="hidden" id="slot" value="${p.slot}">`}
    <input type="hidden" id="ot_id" value="${p.ot_id}">
    <div class="pokemon-form-top">
      <div class="pokemon-form-left">
        <div class="form-grid pid-grid">
        ${field("personality","PID",p.personality,true)}
          ${binaryToggleField("is_shiny", "闪光", p.is_shiny)}
        </div>
        ${field("species","种族",idName(p.species, p.species_name),false,"species-list", "handleSpeciesChanged()")}
        <div id="form-types">${pokemonTypeBadges(speciesTypesForForm(p.species, p.types))}</div>
        ${field("held_item","携带道具",idName(p.held_item, p.held_item_name),false,"item-list")}
      </div>
      <div class="pokemon-form-sprite-wrap">
        ${spriteCanvasTag("form", p.species, p.is_shiny, "pokemon-form-sprite")}
      </div>
    </div>
    <div class="trait-row">
      ${abilityField(p.ability_bit, constraints, p.ability_id, p.ability_name)}
      ${natureField(p.nature_id)}
      ${ballField(p.caught_ball)}
    </div>
    <div class="status-row">
      <div class="status-pack">
        ${binaryToggleField("is_egg", "蛋", p.is_egg)}
        ${friendshipField(p.friendship, p.is_egg)}
      </div>
      ${field("level","等级",p.level || 1,false,"", "handleLevelChanged()")}
      ${genderField(p.gender, constraints)}
    </div>
    <div class="stats-row">
      ${statSpreadField("ivs","个体值",p.ivs.join(","))}
      ${statSpreadField("evs","努力值",p.evs.join(","))}
    </div>
    <div id="move-controls">${moveFields(p.moves, p.pps, constraints)}</div>
    <div id="form-encounters">${pokemonEncounterPanel(p.species)}</div>
    <p><button type="button" class="primary" onclick="updatePokemon()">写入宝可梦</button></p>`;
  renderSpritesIn(document.getElementById("form"));
  syncPokemonFormTopSquare();
  requestAnimationFrame(syncPokemonFormTopSquare);
}
async function selectBox(i) {
  const wasSelected = isPokemonSelected("box", i);
  selected = {kind: "box", index: i};
  markPokemonSelection();
  const p = state.boxes[i];
  setInspector(`${p.species_name} · 盒子 ${p.box}-${p.box_slot}`, p.legality.join("\n"));
  if (wasSelected && pokemonFormMatches("box", p)) return;
  pokemonFormConstraints = await loadPokemonConstraints(p.species, p.level || 100);
  renderPokemonForm(p, pokemonFormConstraints, "box");
}
async function updatePokemon() {
  const location = val("location");
  const ids = ["location","species","held_item","nature_id","gender","is_shiny","caught_ball","friendship","evs","ivs","ability_bit","is_egg"];
  const body = {};
  ids.forEach(id => body[id] = val(id));
  if (location === "box") {
    body.box = val("box");
    body.box_slot = val("box_slot");
  } else {
    body.slot = val("slot");
  }
  body.level = val("level");
  body.moves = [0,1,2,3].map(i => num(`move_${i}`));
  body.pps = [0,1,2,3].map(i => ppFromMoveSlot(i));
  const data = await request("/api/pokemon", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
  setStatus(data.message + "\n尚未保存到文件");
  await refresh();
}
function natureField(current) {
  const names = ["勤奋","怕寂寞","勇敢","固执","顽皮","大胆","坦率","悠闲","淘气","乐天","胆小","急躁","认真","爽朗","天真","内敛","慢吞吞","冷静","害羞","马虎","温和","温顺","自大","慎重","浮躁"];
  return `<label>性格<select id="nature_id">${names.map((name, id) => `<option value="${id}" ${id===current?"selected":""}>#${id} · ${name}</option>`).join("")}</select></label>`;
}
function genderField(current, constraints=null) {
  const values = constraints?.gender_options?.length ? constraints.gender_options : ["雄","雌","无性别"];
  return `<label>性别<select id="gender">${values.map(v => `<option value="${v}" ${v===current?"selected":""}>${v}</option>`).join("")}</select></label>`;
}
function abilityField(current, constraints=null, currentAbilityId="", currentAbilityName="") {
  const values = constraints?.ability_options?.length
    ? constraints.ability_options
    : [{bit: current, id: currentAbilityId, name: currentAbilityName || "当前特性"}];
  return `<label>特性<select id="ability_bit">${values.map(a => `<option value="${a.bit}" ${Number(a.bit)===Number(current)?"selected":""}>${abilityLabel(a)}</option>`).join("")}</select></label>`;
}
function abilityLabel(ability) {
  const id = ability.id !== "" && ability.id !== undefined ? `#${ability.id} · ` : "";
  return `${id}${escapeHtml(ability.name || "未知特性")}`;
}
function ballField(current) {
  const names = ["无","大师球","高级球","超级球","精灵球","狩猎球","捕网球","潜水球","巢穴球","重复球","计时球","豪华球","纪念球"];
  const options = Array.from({length: 16}, (_, id) => {
    const name = names[id] || `球 ${id}`;
    return `<option value="${id}" ${Number(id)===Number(current)?"selected":""}>#${id} · ${escapeHtml(name)}</option>`;
  }).join("");
  return `<label>捕获球<select id="caught_ball">${options}</select></label>`;
}
function friendshipField(current, isEgg) {
  return `<label><span id="friendship_label">${friendshipLabel(isEgg)}</span><span id="friendship_hint" class="hint-mark" data-tip="${escapeHtml(friendshipHint(isEgg))}">?</span><input id="friendship" value="${current}"></label>`;
}
function statSpreadField(id, label, value) {
  return `<label>${label}<span class="hint-mark" data-tip="顺序：体力/物攻/物防/速度/特攻/特防">?</span><input id="${id}" value="${value}"></label>`;
}
function friendshipLabel(isEgg) {
  return Number(isEgg) ? "孵化周期" : "亲密度";
}
function friendshipHint(isEgg) {
  return Number(isEgg) ? "数值越小越接近孵化；0 表示可孵化。" : "普通宝可梦使用亲密度；蛋会把同一字节解释为孵化周期。";
}
function updateFriendshipLabel() {
  const label = document.getElementById("friendship_label");
  const hint = document.getElementById("friendship_hint");
  const egg = document.getElementById("is_egg");
  if (label && egg) label.textContent = friendshipLabel(Number(egg.value));
  if (hint && egg) hint.dataset.tip = friendshipHint(Number(egg.value));
}
function binaryToggleField(id, label, current) {
  const value = current ? 1 : 0;
  return `<label class="toggle-field">${label}<input type="hidden" id="${id}" value="${value}"><button type="button" class="single-toggle ${value ? "active" : ""}" onclick="toggleBinaryValue('${id}')"><span class="track"><span class="thumb"></span></span></button></label>`;
}
function toggleBinaryValue(id) {
  const current = Number(val(id) || 0);
  setBinaryToggleValue(id, current ? 0 : 1);
}
function setBinaryToggleValue(id, value) {
  const input = document.getElementById(id);
  if (!input) return;
  input.value = String(value);
  syncBinaryToggleDisplay(id, value);
  if (id === "is_egg") updateFriendshipLabel();
  if (id === "is_shiny") {
    refreshFormSprite();
    refreshAdjustedPersonalityFields();
  }
}
function syncBinaryToggleDisplay(id, value) {
  const button = document.querySelector(`#${id} + .single-toggle`);
  if (!button) return;
  button.classList.toggle("active", Number(value) === 1);
}
function moveFields(moves, pps, constraints=null) {
  const groups = buildMoveOptionGroups(moves, constraints);
  const options = flattenMoveGroups(groups);
  const validMoveIds = new Set((constraints?.moves || []).map(m => Number(m.id)));
  const constraintsAvailable = constraints?.available !== false && Boolean(constraints?.moves);
  return [0,1,2,3].map(i => `
    <div class="move-grid">
      <label>招式 ${i + 1}
        <select id="move_${i}" class="${isInvalidMove(moves[i], validMoveIds, constraintsAvailable) ? "invalid-move" : ""}" onfocus="setMoveSelectDetailed(this, true)" onmousedown="setMoveSelectDetailed(this, true)" onblur="setMoveSelectDetailed(this, false)" onchange="syncMovePp(${i}); setMoveSelectDetailed(this, false)">
          ${renderMoveOptionGroups(groups, moves[i])}
        </select>
      </label>
      <label>PP提升
        <input type="hidden" id="pp_up_${i}" value="${ppUpsForMove(moves[i], pps[i], options)}" data-current-pp="${pps[i] ?? 0}">
        <span class="pp-up-control">${ppUpButtons(i, ppUpsForMove(moves[i], pps[i], options))}</span>
      </label>
    </div>`).join("");
}
function isInvalidMove(moveId, validMoveIds, constraintsAvailable) {
  const id = Number(moveId);
  if (!id || !constraintsAvailable) return false;
  return !validMoveIds.has(id);
}
function buildMoveOptionGroups(currentMoves, constraints=null) {
  const seen = new Set();
  const groups = [
    {label: "空", rows: [{id:0, pp:0, label:"0 空", disabled:false}]},
    {label: "升级招式", rows: []},
    {label: "遗传招式", rows: []},
    {label: "定点教学", rows: []},
    {label: "TM/HM", rows: []},
    {label: "不合法招式", rows: []},
  ];
  seen.add(0);
  function add(groupLabel, id, name, pp, sources, disabled=false) {
    if (seen.has(Number(id))) return;
    seen.add(Number(id));
    const suffix = sources && sources.length ? ` [${sources.join("/")}]` : "";
    const shortLabel = `#${id} · ${name}`;
    const group = groups.find(g => g.label === groupLabel) || groups[groups.length - 1];
    group.rows.push({id, pp, shortLabel, label:`${shortLabel}${suffix}`, disabled});
  }
  [...(constraints?.moves || []), ...(constraints?.future_moves || [])]
    .filter(m => hasLevelSource(m))
    .sort((a, b) => earliestLearnLevel(a) - earliestLearnLevel(b) || Number(a.id) - Number(b.id))
    .forEach(m => add("升级招式", m.id, m.name, m.pp, m.sources, isFutureOnlyMove(m)));
  (constraints?.moves || [])
    .filter(m => hasEggSource(m))
    .sort((a, b) => Number(a.id) - Number(b.id))
    .forEach(m => add("遗传招式", m.id, m.name, m.pp, m.sources, false));
  (constraints?.moves || [])
    .filter(m => hasTutorSource(m))
    .sort((a, b) => tutorSort(a) - tutorSort(b) || Number(a.id) - Number(b.id))
    .forEach(m => add("定点教学", m.id, m.name, m.pp, m.sources, false));
  (constraints?.moves || [])
    .filter(m => hasSourcePrefix(m, "TM/HM"))
    .sort((a, b) => tmhmSort(a) - tmhmSort(b) || Number(a.id) - Number(b.id))
    .forEach(m => add("TM/HM", m.id, m.name, m.pp, m.sources, false));
  currentMoves.forEach(id => {
    if (!seen.has(Number(id))) {
      const row = (names?.moves || []).find(m => Number(m.id) === Number(id));
      add("不合法招式", id, row?.name || `招式 ${id}`, row?.pp || 0, ["不合法"], false);
    }
  });
  return groups.filter(g => g.rows.length);
}
function renderMoveOptionGroups(groups, currentMove) {
  return groups.map(group => {
    if (group.label === "空") {
      return group.rows.map(o => moveOptionHtml(o, currentMove)).join("");
    }
    return `<optgroup label="${escapeHtml(group.label)}">${group.rows.map(o => moveOptionHtml(o, currentMove)).join("")}</optgroup>`;
  }).join("");
}
function moveOptionHtml(option, currentMove) {
  const shortLabel = option.shortLabel || option.label;
  return `<option value="${option.id}" data-pp="${option.pp || 0}" data-short="${escapeHtml(shortLabel)}" data-detail="${escapeHtml(option.label)}" ${option.disabled?"disabled":""} ${Number(option.id)===Number(currentMove)?"selected":""}>${escapeHtml(shortLabel)}</option>`;
}
function flattenMoveGroups(groups) {
  return groups.flatMap(group => group.rows);
}
function setMoveSelectDetailed(select, detailed) {
  Array.from(select.options).forEach(option => {
    option.textContent = detailed ? (option.dataset.detail || option.textContent) : (option.dataset.short || option.textContent);
  });
}
function hasSourcePrefix(move, prefix) {
  return (move.sources || []).some(source => String(source).startsWith(prefix));
}
function hasEggSource(move) {
  return (move.sources || []).some(source => String(source).endsWith("遗传"));
}
function hasLevelSource(move) {
  return (move.sources || []).some(source => /Lv\d+/.test(String(source)));
}
function hasTutorSource(move) {
  return hasSourcePrefix(move, "定点教学");
}
function isFutureOnlyMove(move) {
  return !(move.current_levels || []).length && (move.future_levels || []).length > 0;
}
function earliestLearnLevel(move) {
  const levels = [
    ...(move.current_levels || []),
    ...(move.future_levels || []),
    ...levelNumbersFromSources(move.sources || []),
  ].map(Number);
  return levels.length ? Math.min(...levels) : 999;
}
function levelNumbersFromSources(sources) {
  return sources.flatMap(source => Array.from(String(source).matchAll(/Lv(\d+)/g), match => Number(match[1])));
}
function tmhmSort(move) {
  const source = (move.sources || []).find(source => String(source).startsWith("TM/HM")) || "";
  const match = String(source).match(/\d+/);
  return match ? Number(match[0]) : 999;
}
function tutorSort(move) {
  const source = (move.sources || []).find(source => String(source).startsWith("定点教学")) || "";
  const match = String(source).match(/\d+/);
  return match ? Number(match[0]) : 999;
}
function syncMovePp(index) {
  const move = document.getElementById(`move_${index}`);
  const ppUp = document.getElementById(`pp_up_${index}`);
  if (Number(move.value) === 0) ppUp.value = 0;
}
function ppUpButtons(index, current) {
  return [0,1,2,3].map(value => `<button type="button" class="${Number(value)===Number(current)?"active":""}" onclick="setPpUp(${index}, ${value})">+${value}</button>`).join("");
}
function setPpUp(index, value) {
  document.getElementById(`pp_up_${index}`).value = value;
  document.querySelectorAll(`#pp_up_${index} + .pp-up-control button`).forEach((button, i) => button.classList.toggle("active", i === value));
}
function ppUpsForMove(moveId, currentPp, options) {
  const id = Number(moveId);
  if (!id) return 0;
  const row = options.find(o => Number(o.id) === id);
  const base = Number(row?.pp || defaultMovePp(id));
  if (!base) return 0;
  const pp = Number(currentPp || 0);
  for (let ups = 0; ups <= 3; ups++) {
    if (pp <= ppFromBaseAndUps(base, ups)) return ups;
  }
  return 3;
}
function ppFromMoveSlot(index) {
  const move = document.getElementById(`move_${index}`);
  const ppUp = document.getElementById(`pp_up_${index}`);
  const id = Number(move?.value || 0);
  if (!id) return 0;
  const selected = move?.options?.[move.selectedIndex];
  const base = Number(selected?.dataset?.pp || defaultMovePp(id));
  if (!base) return Number(ppUp?.dataset?.currentPp || 0);
  return ppFromBaseAndUps(base, Number(ppUp?.value || 0));
}
function ppFromBaseAndUps(base, ups) {
  return Math.floor(Number(base || 0) * (5 + Number(ups || 0)) / 5);
}
function defaultMovePp(moveId) {
  const row = (names?.moves || []).find(m => Number(m.id) === Number(moveId));
  return Number(row?.pp || 0);
}
async function loadPokemonConstraints(species, level) {
  try {
    const data = await request(`/api/pokemon_constraints?species=${encodeURIComponent(species)}&level=${encodeURIComponent(level)}`);
    if (data && data.available === false) setStatus(data.message || "未加载 ROM 约束数据");
    return data;
  } catch (error) {
    setStatus(error.message);
    return null;
  }
}
async function handleSpeciesChanged() {
  await syncExperienceFromLevel();
  await refreshPokemonConstraintsFromForm({resetMoves: true, resetAbility: true});
  refreshFormSpeciesMeta();
  refreshFormSprite();
  await refreshPersonalityDerivedFields();
}
async function handleLevelChanged() {
  await syncExperienceFromLevel();
  await refreshPokemonConstraintsFromForm();
}
async function refreshPokemonConstraintsFromForm(options={}) {
  const species = idNum("species");
  const level = num("level");
  pokemonFormConstraints = await loadPokemonConstraints(species, level);
  const moves = options.resetMoves ? defaultMovesForConstraints(pokemonFormConstraints) : [0,1,2,3].map(i => num(`move_${i}`));
  const pps = options.resetMoves ? moves.map(id => defaultMovePp(id)) : [0,1,2,3].map(i => ppFromMoveSlot(i));
  const currentGender = val("gender");
  const currentAbility = val("ability_bit");
  const nextAbility = options.resetAbility ? defaultAbilityBit(pokemonFormConstraints, currentAbility) : currentAbility;
  const genderWrapper = document.getElementById("gender").parentElement;
  const abilityWrapper = document.getElementById("ability_bit").parentElement;
  genderWrapper.outerHTML = genderField(currentGender, pokemonFormConstraints);
  abilityWrapper.outerHTML = abilityField(nextAbility, pokemonFormConstraints);
  document.getElementById("move-controls").innerHTML = moveFields(moves, pps, pokemonFormConstraints);
}
function defaultAbilityBit(constraints, current) {
  const options = constraints?.ability_options || [];
  if (!options.length) return current;
  if (options.some(a => Number(a.bit) === Number(current))) return current;
  return options[0].bit;
}
function defaultMovesForConstraints(constraints) {
  const levelMoves = (constraints?.moves || [])
    .filter(m => m.current_levels?.length)
    .map(m => ({...m, learnLevel: Math.max(...m.current_levels.map(Number))}))
    .sort((a, b) => a.learnLevel - b.learnLevel || Number(a.id) - Number(b.id));
  const moves = levelMoves.slice(-4).map(m => Number(m.id));
  while (moves.length < 4) moves.push(0);
  return moves;
}
async function refreshPersonalityDerivedFields() {
  const species = idNum("species");
  const personality = num("personality");
  const otId = num("ot_id");
  if (![species, personality, otId].every(Number.isFinite)) {
    setStatus("无法预览 PID：缺少种族、PID 或 OT ID 数据");
    return;
  }
  try {
    const data = await request(`/api/personality_preview?species=${encodeURIComponent(species)}&personality=${encodeURIComponent(personality)}&ot_id=${encodeURIComponent(otId)}`);
    if (data.ok) {
      document.getElementById("nature_id").value = data.nature_id;
      document.getElementById("gender").value = data.gender;
      setBinaryToggleValue("is_shiny", data.is_shiny ? 1 : 0);
    }
  } catch (error) {
    setStatus(error.message);
  }
}
async function refreshAdjustedPersonalityFields() {
  const species = idNum("species");
  const personality = num("personality");
  const otId = num("ot_id");
  const natureId = num("nature_id");
  const gender = val("gender");
  const shiny = val("is_shiny");
  if (![species, personality, otId, natureId].every(Number.isFinite)) {
    setStatus("无法调整 PID：缺少种族、PID、OT ID 或性格数据");
    return;
  }
  try {
    const data = await request(`/api/personality_adjust?species=${encodeURIComponent(species)}&personality=${encodeURIComponent(personality)}&ot_id=${encodeURIComponent(otId)}&nature_id=${encodeURIComponent(natureId)}&gender=${encodeURIComponent(gender)}&is_shiny=${encodeURIComponent(shiny)}`);
    if (data.ok) {
      document.getElementById("personality").value = data.personality;
      document.getElementById("nature_id").value = data.nature_id;
      document.getElementById("gender").value = data.gender;
      document.getElementById("is_shiny").value = data.is_shiny ? "1" : "0";
      syncBinaryToggleDisplay("is_shiny", data.is_shiny ? 1 : 0);
      refreshFormSprite();
    }
  } catch (error) {
    setStatus(error.message);
  }
}
async function syncExperienceFromLevel() {
  const species = idNum("species");
  const level = num("level");
  const experience = 0;
  await loadExperienceLevel(species, level, experience);
}
async function loadExperienceLevel(species, level, experience) {
  try {
    const data = await request(`/api/experience_level?species=${encodeURIComponent(species)}&level=${encodeURIComponent(level)}&experience=${encodeURIComponent(experience)}`);
    if (data && data.available === false) setStatus(data.message || "未加载 ROM 经验曲线数据");
    return data;
  } catch (error) {
    setStatus(error.message);
    return null;
  }
}
function renderNames() {
  if (!names) return;
  const dictionaryTabs = [["species", "宝可梦"], ["abilities", "特性"], ["moves", "招式"], ["items", "道具"], ["type_chart", "属性克制"]];
  if (!dictionaryTabs.some(([id]) => id === collectTable)) collectTable = "species";
  const isTypeChart = collectTable === "type_chart";
  const rows = isTypeChart ? [] : filteredNameRows();
  const dictionaryTabButtons = dictionaryTabs.map(([id, label]) => `<button class="${collectTable===id?"active":""}" onclick="setCollectTable('${escapeJsString(id)}')">${escapeHtml(label)}</button>`).join("");
  document.getElementById("summary").textContent = "";
  let html = `
    <div class="tabs subtabs dictionary-tabs">
      ${dictionaryTabButtons}
      ${isTypeChart ? "" : `<input value="${escapeHtml(collectSearch)}" onchange="setCollectSearch(this.value)" placeholder="按 ID、名称、说明搜索">`}
      ${!isTypeChart && collectCodeFilter.length ? `<span class="badge">${escapeHtml(collectCodeLabel)} ${collectCodeFilter.length} 个 <button type="button" onclick="clearCollectCodeFilter()">清除</button></span>` : ""}
      <span class="badge">${isTypeChart ? `${TYPE_CHART_IDS.length} 属性` : `${rows.length}/${names.rows.length}`}</span>
      ${isTypeChart ? "" : `<button type="button" onclick="reloadNames()">刷新</button>`}
    </div>
    ${isTypeChart ? renderTypeChart() : renderDictionaryTable(rows)}`;
  document.getElementById("content").innerHTML = html;
  if (isTypeChart) setInspector("属性克制表", "行表示攻击属性，列表示防守属性。组合防守会把两个防守属性的倍率相乘。");
  else setInspector("未选择字典项");
}
function renderDictionaryTable(rows) {
  const columns = dictionaryColumns(collectTable);
  const head = columns.map(col => `<th>${escapeHtml(col.label)}</th>`).join("");
  const body = rows.map(({r, idx}) => {
    const selectedClass = selected && selected.table === r.table && selected.id === r.id ? "selected" : "";
    const cells = columns.map(col => `<td class="${col.className || ""}">${dictionaryCell(r, col.key)}</td>`).join("");
    return `<tr id="rom-${r.table}-${r.id}" class="${selectedClass}" onclick="selectNameIndex(${idx})">${cells}</tr>`;
  }).join("");
  return `<table class="dictionary-table dictionary-${collectTable}"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}
function dictionaryColumns(table) {
  const common = [{key:"id", label:"ID"}, {key:"name", label:"名称", className:"name-cell"}];
  if (table === "species") {
    return [...common, {key:"types", label:"属性", className:"types-cell"}, {key:"baseStats", label:"种族值"}, {key:"abilities", label:"特性"}, {key:"growthRate", label:"经验曲线"}, {key:"genderRatio", label:"性别"}, {key:"encounters", label:"Encounter"}, {key:"locations", label:"存档引用"}];
  }
  if (table === "moves") {
    return [...common, {key:"pp", label:"PP"}, {key:"description", label:"描述", className:"description-cell"}, {key:"locations", label:"存档引用"}];
  }
  if (table === "abilities") {
    return [...common, {key:"description", label:"描述", className:"description-cell"}, {key:"locations", label:"存档引用"}];
  }
  if (table === "items") {
    return [...common, {key:"pocket", label:"口袋"}, {key:"price", label:"价格"}, {key:"itemType", label:"类型"}, {key:"holdEffect", label:"携带效果"}, {key:"description", label:"描述", className:"description-cell"}, {key:"locations", label:"存档引用"}];
  }
  return [{key:"table", label:"类型"}, ...common, {key:"summary", label:"摘要", className:"description-cell"}, {key:"locations", label:"存档引用"}];
}
function dictionaryCell(row, key) {
  const detail = row.detail || {};
  if (key === "id") return `<span class="num">#${row.id}</span>`;
  if (key === "table") return escapeHtml(row.table_label || row.table || "");
  if (key === "name") return dictionaryNameCell(row);
  if (key === "tokens") return escapeHtml((row.tokens || []).join(" ") || "无");
  if (key === "locations") return dictionaryLocationsCell(row);
  if (key === "summary") return escapeHtml(summaryForDictionaryRow(row) || row.description || "");
  if (key === "description") return escapeHtml(row.description || detail.description_note || "");
  if (key === "types") return pokemonTypeBadges(detail.types || []);
  if (key === "baseStats") return baseStatsInline(detail.base_stats);
  if (key === "abilities") return chipList((detail.abilities || []).map(a => `#${a.id} ${a.name}`));
  if (key === "growthRate") return escapeHtml(detail.growth_rate || "");
  if (key === "genderRatio") return escapeHtml(detail.gender_ratio || "");
  if (key === "encounters") return escapeHtml(encounterSummary(detail.encounters || []));
  if (key === "pp") return `<span class="num">${row.pp ?? detail.pp ?? ""}</span>`;
  if (key === "pocket") return escapeHtml(detail.pocket || "");
  if (key === "price") return detail.price !== undefined ? `<span class="num">${detail.price}</span>` : "";
  if (key === "itemType") return escapeHtml(detail.type || "");
  if (key === "holdEffect") return detail.hold_effect !== undefined ? escapeHtml(`${detail.hold_effect} / 参数 ${detail.hold_param}`) : "";
  return "";
}
function dictionaryNameCell(row) {
  const decoded = row.decoded || row.name || "";
  const unknown = row.unknown_count ? ` <span class="bad" title="未知字符数量">${row.unknown_count}</span>` : "";
  return `${escapeHtml(decoded)}${unknown}`;
}
function dictionaryLocationsCell(row) {
  const locations = row.locations || [];
  if (locations.length) return dictionaryLocationButtons(locations, 4);
  return row.observed ? "已引用" : `<span class="muted">未引用</span>`;
}
function dictionaryLocationButtons(locations, limit=0) {
  const visible = limit ? locations.slice(0, limit) : locations;
  const more = limit && locations.length > limit ? `<span class="muted">+${locations.length - limit}</span>` : "";
  return `<span class="chip-list">${visible.map(location => `<button type="button" class="data-chip location-link" onclick="jumpToSaveLocation('${escapeJsString(location)}'); event.stopPropagation();">${escapeHtml(location)}</button>`).join("")}${more}</span>`;
}
async function jumpToSaveLocation(label) {
  if (!state?.ok) return;
  const clean = String(label || "").replace(/\s+携带$/, "").replace(/\s+x\d+$/, "").trim();
  const party = clean.match(/^队伍 #?(\d+)$/);
  if (party) {
    const slot = Number(party[1]);
    const index = state.party.findIndex(p => Number(p.slot) === slot);
    if (index >= 0) {
      tab = "pokemon";
      pokemonView = "party";
      selected = {kind: "party", index};
      render();
      await selectParty(index);
      scrollToSaveAnchor(`save-party-${index}`);
      setStatus(`已跳转到${label}`);
    }
    return;
  }
  const box = clean.match(/^盒子 (\d+)-(\d+)$/);
  if (box) {
    const boxNo = Number(box[1]);
    const boxSlot = Number(box[2]);
    const index = state.boxes.findIndex(p => Number(p.box) === boxNo && Number(p.box_slot) === boxSlot);
    if (index >= 0) {
      tab = "pokemon";
      pokemonView = String(boxNo);
      selected = {kind: "box", index};
      render();
      await selectBox(index);
      scrollToSaveAnchor(`save-box-${index}`);
      setStatus(`已跳转到${label}`);
    }
    return;
  }
  const bag = clean.match(/^(.+) #(\d+)$/);
  if (bag) {
    const pocket = bag[1];
    const slot = Number(bag[2]);
    const index = state.bag.findIndex(e => e.pocket === pocket && Number(e.slot) === slot);
    if (index >= 0) {
      tab = "bag";
      bagPocket = pocket;
      selected = index;
      render();
      selectBag(index);
      scrollToSaveAnchor(`save-bag-${index}`);
      setStatus(`已跳转到${label}`);
    }
  }
}
function scrollToSaveAnchor(id) {
  requestAnimationFrame(() => {
    const target = document.getElementById(id);
    if (target) target.scrollIntoView({block: "center"});
  });
}
function chipList(values, extraClass="") {
  const items = (values || []).filter(Boolean);
  if (!items.length) return "";
  return `<span class="chip-list">${items.map(value => `<span class="data-chip ${extraClass}">${escapeHtml(value)}</span>`).join("")}</span>`;
}
function baseStatsInline(stats) {
  if (!stats) return "";
  const values = [["HP", stats.hp], ["攻", stats.attack], ["防", stats.defense], ["速", stats.speed], ["特攻", stats.sp_attack], ["特防", stats.sp_defense]];
  return `<span class="base-stat-grid">${values.map(([label, value]) => `<span class="base-stat"><span class="base-stat-label">${label}</span><span class="base-stat-value">${value}</span></span>`).join("")}</span>`;
}
function encounterSummary(encounters) {
  if (!encounters?.length) return "";
  const first = encounters.slice(0, 3).map(encounterLabel).join("；");
  return encounters.length > 3 ? `${first}；+${encounters.length - 3}` : first;
}
function encounterLabel(encounter) {
  const level = encounter.min_level === encounter.max_level ? `Lv${encounter.min_level}` : `Lv${encounter.min_level}-${encounter.max_level}`;
  return `${encounter.location} ${encounter.method} ${level}`;
}
function renderTypeChart() {
  const profile = typeDefenseProfile(typeDefenseA, typeDefenseB);
  const head = `<tr><th>攻击 \\ 防守</th>${TYPE_CHART_IDS.map(id => `<th>${escapeHtml(TYPE_NAMES[id])}</th>`).join("")}</tr>`;
  const body = TYPE_CHART_IDS.map((attackId) => {
    const attackName = TYPE_NAMES[attackId];
    const cells = TYPE_CHART_IDS.map((defenseId) => {
      const defenseName = TYPE_NAMES[defenseId];
      const value = typeEffectiveness(attackId, defenseId);
      return `<td class="${effectClass(value)}" title="${escapeHtml(attackName)} 攻击 ${escapeHtml(defenseName)}">${effectLabel(value)}</td>`;
    }).join("");
    return `<tr><th>${escapeHtml(attackName)}</th>${cells}</tr>`;
  }).join("");
  return `
    <div class="type-tools">
      <label>防守属性 1 <select onchange="setTypeDefense(1, this.value)">${typeOptions(typeDefenseA, false)}</select></label>
      <label>防守属性 2 <select onchange="setTypeDefense(2, this.value)">${typeOptions(typeDefenseB, true)}</select></label>
      <span class="badge">第三世代属性表</span>
      <span class="badge">钢抵抗幽灵/恶</span>
    </div>
    <div class="type-profile">
      ${typeProfileGroup("4 倍弱点", profile[4])}
      ${typeProfileGroup("2 倍弱点", profile[2])}
      ${typeProfileGroup("1/2 抵抗", profile[0.5])}
      ${typeProfileGroup("1/4 抵抗", profile[0.25])}
      ${typeProfileGroup("免疫", profile[0])}
      ${typeProfileGroup("正常伤害", profile[1])}
    </div>
    <div class="type-chart-wrap"><table class="type-chart"><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
}
function typeOptions(selected, allowEmpty) {
  const empty = allowEmpty ? `<option value="" ${selected === "" || selected === null || selected === undefined ? "selected" : ""}>无</option>` : "";
  return empty + TYPE_CHART_IDS.map(id => `<option value="${id}" ${Number(selected) === id ? "selected" : ""}>${escapeHtml(TYPE_NAMES[id])}</option>`).join("");
}
function setTypeDefense(slot, value) {
  const parsed = value === "" ? "" : Number(value);
  if (slot === 1) typeDefenseA = parsed;
  else typeDefenseB = parsed;
  renderNames();
}
function typeEffectiveness(attackId, defenseId) {
  return TYPE_EFFECTIVENESS[`${attackId}>${defenseId}`] ?? 1;
}
function dualTypeEffectiveness(attackId, defenseA, defenseB) {
  const first = defenseA === "" || defenseA === null || defenseA === undefined ? 1 : typeEffectiveness(attackId, Number(defenseA));
  const second = defenseB === "" || defenseB === null || defenseB === undefined || Number(defenseB) === Number(defenseA) ? 1 : typeEffectiveness(attackId, Number(defenseB));
  return first * second;
}
function typeDefenseProfile(defenseA, defenseB) {
  const profile = {0: [], 0.25: [], 0.5: [], 1: [], 2: [], 4: []};
  TYPE_CHART_IDS.forEach((attackId) => {
    const name = TYPE_NAMES[attackId];
    const value = dualTypeEffectiveness(attackId, defenseA, defenseB);
    (profile[value] || profile[1]).push(name);
  });
  return profile;
}
function typeProfileGroup(title, values) {
  return `<div class="detail-field"><h4>${escapeHtml(title)}</h4>${values.length ? chipList(values, "type-chip") : `<span class="muted">无</span>`}</div>`;
}
function effectLabel(value) {
  if (value === 0.25) return "1/4";
  if (value === 0.5) return "1/2";
  return `${value}x`;
}
function effectClass(value) {
  return `effect-${String(value).replace(".", "")}`;
}
function filteredNameRows() {
  const q = collectSearch.trim().toLowerCase();
  const rows = names.rows
    .map((r, idx) => ({r, idx}))
    .filter(({r}) => r.table === collectTable)
    .filter(({r}) => !collectCodeFilter.length || (r.tokens || []).some(token => collectCodeFilter.includes(String(token).toUpperCase())))
    .filter(({r}) => !q || String(r.id).includes(q) || String(r.decoded || r.name || "").toLowerCase().includes(q) || String(r.description || "").toLowerCase().includes(q) || detailLinesForDictionaryRow(r).join(" ").toLowerCase().includes(q));
  return rows.map(row => ({...row, location: ""}));
}
function setCollectTable(next) { collectTable = next; renderNames(); }
function setCollectSearch(next) { collectSearch = next; collectCodeFilter = []; collectCodeLabel = ""; renderNames(); }
function clearCollectCodeFilter() { collectCodeFilter = []; collectCodeLabel = ""; renderNames(); }
function jumpToCharmapCodes(kind) {
  const charmap = names?.stats?.charmap || {};
  const codes = charmap.rom_unknown_codes || [];
  collectSearch = "";
  collectCodeFilter = codes.map(code => String(code).toUpperCase()).filter(Boolean);
  collectCodeLabel = "未知字符";
  const rows = (names?.rows || [])
    .map((r, idx) => ({r, idx}))
    .filter(({r}) => (r.tokens || []).some(token => collectCodeFilter.includes(String(token).toUpperCase())));
  if (!rows.length) {
    collectTable = "species";
    renderNames();
    setStatus(`${collectCodeLabel} 没有匹配到当前字典行`);
    return;
  }
  const first = rows[0];
  collectTable = first.r.table;
  selected = {table: first.r.table, id: first.r.id};
  renderNames();
  const target = document.getElementById(`rom-${first.r.table}-${first.r.id}`);
  if (target) target.scrollIntoView({block: "center"});
  selectNameIndex(first.idx);
}
async function reloadNames() {
  names = await request("/api/names");
  renderNames();
}
function nameRow(table, id) {
  const tableRows = names?.[table] || [];
  return tableRows.find(row => row.id === id);
}
function nameIndex(table, id) {
  return (names?.rows || []).findIndex(row => row.table === table && row.id === id);
}
function selectNameRow(table, id) {
  const row = nameRow(table, id);
  if (!row) return;
  setInspector(`${table} #${id}`, [
    `当前解码：${row.decoded || row.name || ""}`,
    ...detailLinesForDictionaryRow(row),
  ].join("\n"));
}
function selectNameIndex(idx) {
  const row = names.rows[idx];
  if (!row) return;
  selected = {table: row.table, id: row.id};
  setInspectorHtml(`${row.table_label} #${row.id} ${row.decoded || row.name || ""}`, dictionaryInspectorHtml(row));
}
function jumpToRom(table, id) {
  collectTable = table;
  collectSearch = String(id);
  tab = "names";
  selected = {table, id};
  render();
  const target = document.getElementById(`rom-${table}-${id}`);
  if (target) {
    target.scrollIntoView({block: "center"});
    selectNameIndex(nameIndex(table, id));
  }
}
function summaryForDictionaryRow(row) {
  const lines = detailLinesForDictionaryRow(row);
  return lines.slice(0, 2).join("；");
}
function dictionaryInspectorHtml(row) {
  const detail = row.detail || {};
  const fields = [
    ["当前解码", row.decoded || row.name || ""],
  ];
  if (row.description) fields.push(["描述", row.description, true]);
  if (row.table === "moves") {
    fields.push(["PP", row.pp ?? detail.pp ?? ""]);
  }
  if (row.table === "items") {
    fields.push(["口袋", detail.pocket || ""]);
    fields.push(["价格", detail.price]);
    fields.push(["类型", detail.type || ""]);
    fields.push(["携带效果", detail.hold_effect !== undefined ? `${detail.hold_effect} / 参数 ${detail.hold_param}` : ""]);
    fields.push(["Secondary ID", detail.secondary_id]);
  }
  if (row.table === "species") {
    fields.push(["属性", detail.types?.length ? pokemonTypeBadges(detail.types) : "", false, true]);
    if (detail.base_stats) fields.push(["种族值", baseStatsInline(detail.base_stats), true, true]);
    fields.push(["特性", (detail.abilities || []).map(a => `#${a.id} ${a.name}`).join("；")]);
    fields.push(["性别比例", detail.gender_ratio || ""]);
    fields.push(["经验曲线", detail.growth_rate || ""]);
    fields.push(["蛋组", detail.egg_groups?.join(" / ") || ""]);
    fields.push(["孵化周期", detail.egg_cycles]);
    fields.push(["初始亲密度", detail.base_friendship]);
    fields.push(["捕获率", detail.catch_rate]);
    fields.push(["击败经验", detail.exp_yield]);
    fields.push(["野生携带", (detail.wild_items || []).map(item => `#${item.id} ${item.name}`).join("；")]);
    fields.push(["Encounter", (detail.encounters || []).map(encounter => `${encounterLabel(encounter)}，几率 ${encounter.rate}，槽位 ${(encounter.slots || []).join("/")}`).join("；"), true]);
  }
  if (row.locations?.length) fields.push(["存档引用", dictionaryLocationButtons(row.locations), true, true]);
  return `<div class="detail-grid">${fields.filter(([, value]) => value !== undefined && value !== null && String(value) !== "").map(([label, value, wide, html]) => `<div class="detail-field ${wide ? "wide" : ""}"><span class="detail-label">${escapeHtml(label)}</span><div class="detail-value">${html ? value : escapeHtml(value)}</div></div>`).join("")}</div>`;
}
function detailLinesForDictionaryRow(row) {
  const detail = row.detail || {};
  const lines = [];
  if (row.description) lines.push(`描述：${row.description}`);
  if (row.table === "moves") {
    lines.push(`PP：${row.pp ?? detail.pp ?? ""}`);
  }
  if (row.table === "items") {
    if (detail.price !== undefined) lines.push(`价格：${detail.price}`);
    if (detail.pocket) lines.push(`口袋：${detail.pocket}`);
    if (detail.type) lines.push(`类型：${detail.type}`);
    if (detail.hold_effect !== undefined) lines.push(`携带效果：${detail.hold_effect} / 参数 ${detail.hold_param}`);
    if (detail.secondary_id !== undefined) lines.push(`内部 secondary id：${detail.secondary_id}`);
  }
  if (row.table === "species") {
    if (detail.types?.length) lines.push(`属性：${detail.types.join("/")}`);
    if (detail.base_stats) {
      const s = detail.base_stats;
      lines.push(`种族值：HP ${s.hp} / 攻 ${s.attack} / 防 ${s.defense} / 速 ${s.speed} / 特攻 ${s.sp_attack} / 特防 ${s.sp_defense}`);
    }
    if (detail.abilities?.length) lines.push(`特性：${detail.abilities.map(a => `#${a.id} ${a.name}`).join("；")}`);
    if (detail.gender_ratio) lines.push(`性别：${detail.gender_ratio}`);
    if (detail.growth_rate) lines.push(`经验曲线：${detail.growth_rate}`);
    if (detail.egg_groups?.length) lines.push(`蛋组：${detail.egg_groups.join("/")}`);
    if (detail.egg_cycles !== undefined) lines.push(`孵化周期：${detail.egg_cycles}`);
    if (detail.base_friendship !== undefined) lines.push(`初始亲密度：${detail.base_friendship}`);
    if (detail.catch_rate !== undefined) lines.push(`捕获率：${detail.catch_rate}`);
    if (detail.exp_yield !== undefined) lines.push(`击败经验：${detail.exp_yield}`);
    if (detail.wild_items?.length) lines.push(`野生携带：${detail.wild_items.map(item => `#${item.id} ${item.name}`).join("；")}`);
    if (detail.encounters?.length) lines.push(`Encounter：${encounterSummary(detail.encounters)}`);
  }
  return lines.filter(Boolean);
}
function field(id, label, value, readonly=false, list="", onchange="") { return `<label>${label}<input id="${id}" value="${value}" ${list?`list="${list}"`:""} ${readonly?"readonly":""} ${onchange?`onchange="${onchange}"`:""}></label>`; }
function val(id) { return document.getElementById(id).value; }
function num(id) { return parseInt(val(id), 10); }
function idNum(id) { return parseInt(String(val(id)).trim().replace(/^#/, "").split(/\s+/)[0], 10); }
window.addEventListener("resize", () => syncPokemonFormTopSquare());
window.addEventListener("beforeunload", event => {
  if (!state?.dirty) return;
  event.preventDefault();
  event.returnValue = "";
});
refresh().catch(err => setStatus(err.message));
</script>
</body>
</html>
"""


def open_browser(url: str) -> None:
    try:
        subprocess.Popen(["open", url])
    except Exception:
        webbrowser.open(url)


def available_port(host: str, start: int) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise OSError(f"没有可用端口：{start}-{start + 19}")


def main() -> None:
    load_save(DEFAULT_SAVE)
    port = available_port(HOST, PORT)
    server = ThreadingHTTPServer((HOST, port), Handler)
    url = f"http://{HOST}:{port}/"
    threading.Timer(0.5, open_browser, args=(url,)).start()
    print(f"浏览器界面已启动：{url}")
    print("关闭这个终端窗口即可停止服务。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise
