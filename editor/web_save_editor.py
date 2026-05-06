from __future__ import annotations

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
    reload_rom_names,
    validate_pokemon,
)
from rom_data import OUTPUT as ROM_TEXT_OUTPUT, load_rom_text, save_charmap, save_rom_text


DEFAULT_SAVE = Path("/Users/wang.song/Desktop/pokemon/漆黑的魅影 5.0EX BW.sav")
HOST = "127.0.0.1"
PORT = 8765


class State:
    save_path = DEFAULT_SAVE
    save: EmeraldSave | None = None
    error = ""


STATE = State()


def table_sort_rank(table: str) -> int:
    return {"species": 0, "abilities": 1, "moves": 2, "items": 3, "natures": 4, "balls": 5}.get(table, 9)


def load_save(path: Path | None = None) -> None:
    if path is not None:
        STATE.save_path = path
    try:
        STATE.save = EmeraldSave(STATE.save_path)
        STATE.error = ""
    except Exception as exc:
        STATE.save = None
        STATE.error = str(exc)


def response(payload, status=200):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return status, "application/json; charset=utf-8", data


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *args):
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
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
        if parsed.path == "/api/load":
            query = parse_qs(parsed.query)
            path = Path(query.get("path", [str(STATE.save_path)])[0]).expanduser()
            load_save(path)
            self.send(*response(api_state()))
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
            if self.path == "/api/charmap":
                self.send(*response(api_update_charmap(body)))
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
        self.wfile.write(data)


def api_state():
    save = STATE.save
    if not save:
        return {"ok": False, "path": str(STATE.save_path), "error": STATE.error, "bag": [], "party": [], "validation": []}
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
        "path": str(save.path),
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


def pokemon_payload(p, label: str):
    return {
        "slot": p.slot,
        "box": p.box,
        "box_slot": p.box_slot,
        "species": p.species,
        "species_name": p.species_name,
        "personality": p.personality,
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
        "legality": validate_pokemon(p, label, check_level=not p.box, move_level=100 if p.box else None),
    }


def api_names():
    if not ROM_TEXT_OUTPUT.exists():
        load_rom_text()
    raw = load_rom_text()
    observed = observed_from_save()

    def table(name: str, label: str):
        rows = []
        for key, entry in sorted(raw.get(name, {}).items(), key=lambda item: int(item[0])):
            item_id = int(key)
            tokens = entry.get("tokens") or []
            rows.append(
                {
                    "table": name,
                    "table_label": label,
                    "id": item_id,
                    "name": entry.get("name") or "",
                    "decoded": entry.get("decoded") or "",
                    "tokens": tokens,
                    "observed": item_id in observed[name],
                    "locations": observed[name].get(item_id, []),
                    "unknown_count": sum(1 for token in tokens if "{" + token + "}" in (entry.get("decoded") or "")),
                }
            )
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
            "confirmed": int(raw.get("character_map_count", 0)),
            "unresolved": len(raw.get("unresolved_character_codes", [])),
            "candidate_unresolved": len(raw.get("candidate_unresolved_character_codes", [])),
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
    }


def api_pokemon_constraints(species: int, level: int):
    constraints = constraints_for_species(species)
    if constraints is None:
        return {"ok": False, "error": f"无法读取种族 {species} 的 ROM 约束数据"}
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
        elif "遗传" in sources:
            rank = (2, move_id)
        elif any(source.endswith("遗传") for source in sources):
            rank = (3, move_id)
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


def api_update_charmap(body):
    tokens = [str(token).upper() for token in body.get("tokens", [])]
    text = str(body.get("text", "")).strip()
    if not tokens:
        raise ValueError("没有字符码")
    if not text:
        raise ValueError("请填写游戏中看到的文字")
    chars = list(text)
    if len(chars) != len(tokens):
        tokens = coalesce_tokens_for_text(tokens, len(chars))
    if len(chars) != len(tokens):
        raise ValueError(f"填写文字长度 {len(chars)} 与字符码数量 {len(tokens)} 不一致：{' '.join(tokens)}")
    updates = dict(zip(tokens, chars))
    save_charmap(updates)
    save_rom_text()
    reload_rom_names()
    if STATE.save:
        load_save(STATE.save.path)
    return {"ok": True, "message": f"已更新 {len(updates)} 个字符码", "updates": updates}


def coalesce_tokens_for_text(tokens: list[str], target_count: int) -> list[str]:
    """Merge adjacent one-byte tokens when old tokenization split a two-byte character."""
    memo: dict[tuple[int, int], list[str] | None] = {}

    def solve(index: int, remaining: int) -> list[str] | None:
        key = (index, remaining)
        if key in memo:
            return memo[key]
        if remaining < 0:
            return None
        if index == len(tokens):
            return [] if remaining == 0 else None
        keep = solve(index + 1, remaining - 1)
        if keep is not None:
            memo[key] = [tokens[index], *keep]
            return memo[key]
        if (
            index + 1 < len(tokens)
            and len(tokens[index]) == 2
            and len(tokens[index + 1]) == 2
        ):
            merged = tokens[index] + tokens[index + 1]
            use_merged = solve(index + 2, remaining - 1)
            if use_merged is not None:
                memo[key] = [merged, *use_merged]
                return memo[key]
        memo[key] = None
        return None

    return solve(0, target_count) or tokens


def api_update_bag(body):
    save = require_save()
    entry = BagEntry(str(body["pocket"]), int(body["slot"]), int(body["item_id"]), int(body["quantity"]))
    save.write_bag_entry(entry)
    return {"ok": True, "message": f"已写入背包：{entry.pocket} {entry.slot} = {format_item(entry.item_id)} x{entry.quantity}"}


def api_update_pokemon(body):
    save = require_save()
    updates = {
        "species": int(body["species"]),
        "held_item": int(body["held_item"]),
        "experience": int(body["experience"]),
        "friendship": int(body["friendship"]),
        "nature_id": int(body["nature_id"]),
        "gender": str(body["gender"]),
        "is_shiny": bool(int(body["is_shiny"])),
        "moves": parse_list(body["moves"], 4),
        "pps": parse_list(body["pps"], 4),
        "evs": parse_list(body["evs"], 6),
        "ivs": parse_list(body["ivs"], 6),
        "ability_bit": int(body["ability_bit"]),
        "is_egg": bool(int(body["is_egg"])),
    }
    location = str(body.get("location", "party"))
    if location == "box":
        box = int(body["box"])
        box_slot = int(body["box_slot"])
        pokemon = save.update_box_pokemon(box, box_slot, updates)
        return {"ok": True, "message": f"已写入盒子 {box}-{box_slot}：{format_species(pokemon.species)}"}
    slot = int(body["slot"])
    updates["level"] = int(body["level"])
    updates["current_hp"] = int(body["current_hp"])
    pokemon = save.update_party_pokemon(slot, updates)
    return {"ok": True, "message": f"已写入队伍 {slot}：{format_species(pokemon.species)}"}


def api_save():
    save = require_save()
    backup = save.save()
    load_save(save.path)
    return {"ok": True, "message": f"已保存，备份：{backup.name}"}


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


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>漆黑的魅影信息采集器</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", Arial, sans-serif; color: #111; background: #f2f2f2; }
    header { display: flex; gap: 6px; align-items: center; padding: 8px 10px; background: #e4e4e4; border-bottom: 1px solid #ccc; }
    input, select, button, textarea { font: inherit; }
    input, textarea, select { background: white; color: #111; border: 1px solid #aaa; padding: 6px; }
    button { border: 1px solid #777; background: white; color: #111; padding: 5px 9px; cursor: pointer; }
    button.primary { background: #1f6feb; color: white; border-color: #185abc; }
    button.link { border: 0; background: transparent; color: #0969da; padding: 0; text-align: left; text-decoration: underline; }
    #path { flex: 1; }
    main { display: grid; grid-template-columns: minmax(0, 1fr) 280px; gap: 8px; padding: 8px; height: calc(100vh - 45px); }
    .panel { background: white; border: 1px solid #c9c9c9; min-height: 0; }
    .tabs { display: flex; gap: 4px; padding: 6px; background: #eee; border-bottom: 1px solid #ccc; flex-wrap: wrap; }
    .tabs button.active { background: #111; color: white; }
    .dictionary-tabs input { margin-left: auto; width: min(260px, 100%); }
    .summary { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 6px 8px; border-bottom: 1px solid #ddd; font-weight: 600; }
    .summary-controls { display: flex; align-items: center; gap: 6px; font-weight: 400; font-size: 13px; }
    .summary-controls select { padding: 4px 6px; }
    .metrics { display: grid; grid-template-columns: repeat(4, minmax(110px, 1fr)); gap: 6px; padding: 6px; border-bottom: 1px solid #ddd; background: #fafafa; }
    .metric { border: 1px solid #d0d0d0; background: white; padding: 5px 6px; border-radius: 6px; }
    .metric b { display: block; font-size: 16px; margin-bottom: 1px; }
    .filters { display: flex; gap: 6px; align-items: center; padding: 6px; border-bottom: 1px solid #ddd; background: #f7f7f7; flex-wrap: wrap; }
    .filters input { width: min(220px, 100%); }
    .badge { display: inline-block; border: 1px solid #aaa; border-radius: 999px; padding: 1px 7px; font-size: 12px; background: #fff; }
    .bad { color: #b42318; font-weight: 600; }
    .table-wrap { overflow: auto; height: calc(100% - 74px); }
    table { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: auto; }
    th, td { border-bottom: 1px solid #eee; padding: 4px 5px; text-align: left; white-space: normal; vertical-align: top; }
    td input { width: 100%; min-width: 96px; }
    td:nth-child(1), td:nth-child(2), td:nth-child(8) { white-space: nowrap; }
    td:nth-child(3), td:nth-child(4), td:nth-child(5), td:nth-child(6) { max-width: 260px; overflow-wrap: anywhere; }
    th { position: sticky; top: 0; background: #ddd; z-index: 1; }
    tr:hover { background: #edf4ff; }
    tr.selected { background: #cfe2ff; }
    aside { padding: 8px; overflow: auto; }
    aside label { display: block; margin-top: 8px; font-size: 13px; color: #333; }
    aside input, aside select, aside textarea { width: 100%; margin-top: 3px; }
    #detail { height: 120px; white-space: pre-wrap; overflow: auto; background: #fafafa; border: 1px solid #ccc; padding: 8px; }
    #status { margin-top: 10px; color: #333; white-space: pre-wrap; }
    .move-grid { display: grid; grid-template-columns: minmax(0, 1fr) 72px; gap: 6px; align-items: end; margin-top: 8px; }
    .move-grid label { margin-top: 0; }
    .move-grid select, .move-grid input { width: 100%; }
    @media (max-width: 1100px) {
      main { grid-template-columns: 1fr; height: auto; min-height: calc(100vh - 45px); }
      aside { min-height: 170px; }
      .metrics { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
    }
  </style>
</head>
<body>
  <datalist id="species-list"></datalist>
  <datalist id="item-list"></datalist>
  <datalist id="move-list"></datalist>
  <header>
    <span>存档</span>
    <input id="path">
    <button onclick="loadPath()">打开/加载</button>
    <button onclick="reload()">重新加载</button>
  </header>
  <main>
    <section class="panel">
      <div class="tabs">
        <button id="tab-overview" onclick="showTab('overview')">存档概览</button>
        <button id="tab-party" onclick="showTab('party')">队伍</button>
        <button id="tab-boxes" onclick="showTab('boxes')">盒子</button>
        <button id="tab-bag" onclick="showTab('bag')">背包</button>
        <button id="tab-names" onclick="showTab('names')">字典表</button>
      </div>
      <div class="summary" id="summary">加载中</div>
      <div class="table-wrap" id="content"></div>
    </section>
    <aside class="panel">
      <div id="detail">请选择左侧条目</div>
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
let boxView = "all";
let collectTable = "all";
let collectSearch = "";
let pokemonFormConstraints = null;

async function request(url, options) {
  const res = await fetch(url, options);
  const data = await res.json();
  if (!res.ok || data.ok === false) throw new Error(data.error || data.message || "请求失败");
  return data;
}
async function refresh() {
  [state, names] = await Promise.all([request("/api/state"), request("/api/names")]);
  document.getElementById("path").value = state.path || "";
  render();
}
async function loadPath() {
  const p = encodeURIComponent(document.getElementById("path").value);
  state = await request("/api/load?path=" + p);
  names = await request("/api/names");
  selected = null;
  render();
}
async function reload() {
  state = await request("/api/load?path=" + encodeURIComponent(document.getElementById("path").value));
  names = await request("/api/names");
  selected = null;
  render();
}
async function saveFile() {
  const data = await request("/api/save", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"});
  await refresh();
  setStatus(data.message);
}
function showTab(next) { tab = next; selected = null; render(); }
function setStatus(text) { document.getElementById("status").textContent = text; }
function render() {
  renderDatalists();
  for (const id of ["overview","party","boxes","bag","names"]) document.getElementById("tab-"+id).classList.toggle("active", tab === id);
  document.getElementById("form").innerHTML = "";
  document.getElementById("detail").textContent = "请选择左侧条目";
  if (!state || !state.ok) {
    document.getElementById("summary").textContent = "加载失败";
    document.getElementById("content").innerHTML = "<p style='padding:12px'>" + (state?.error || "未知错误") + "</p>";
    return;
  }
  if (tab === "overview") renderOverview();
  if (tab === "bag") renderBag();
  if (tab === "party") renderParty();
  if (tab === "boxes") renderBoxes();
  if (tab === "names") renderNames();
}
function renderDatalists() {
  if (!names) return;
  document.getElementById("species-list").innerHTML = names.species.map(e => `<option value="${e.id}" label="${escapeHtml(e.name)}"></option>`).join("");
  document.getElementById("item-list").innerHTML = names.items.map(e => `<option value="${e.id}" label="${escapeHtml(e.name)}"></option>`).join("");
  document.getElementById("move-list").innerHTML = names.moves.map(e => `<option value="${e.id}" label="${escapeHtml(e.name)}"></option>`).join("");
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
  document.getElementById("detail").textContent = "这里展示已经从当前存档结构中读取的非宝可梦/非背包数据；训练家名字仍按原始字节展示，避免误用 ROM 中文码表。";
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
  rows.forEach(({e, i}) => html += `<tr class="${selected===i?"selected":""}" onclick="selectBag(${i})"><td>${escapeHtml(e.pocket)}</td><td>${e.slot}</td><td>${e.item_id}</td><td>${romLink("items", e.item_id, e.name)}</td><td>${e.quantity}</td></tr>`);
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
  document.getElementById("detail").textContent = `口袋：${e.pocket}\n格位：${e.slot}\n道具：${e.item_id} ${e.name}\n数量：${e.quantity}`;
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
function renderParty() {
  document.getElementById("summary").textContent = `队伍：${state.party.length} 只，当前槽 ${state.active}`;
  let html = "<table><thead><tr><th>槽位</th><th>种族</th><th>等级</th><th>性格</th><th>性别</th><th>特性</th><th>球</th><th>闪光</th><th>HP</th><th>招式</th><th>数据校验</th><th>合法性</th></tr></thead><tbody>";
  state.party.forEach((p, i) => {
    const moves = p.moves.map((id, idx) => romLink("moves", id, p.move_names[idx])).join(" / ");
    html += `<tr onclick="selectParty(${i})"><td>${p.slot}</td><td>${p.species} ${romLink("species", p.species, p.species_name)}</td><td>${p.level}</td><td>${p.nature_name}</td><td>${p.gender}</td><td>${p.ability_id} ${romLink("abilities", p.ability_id, p.ability_name)}</td><td>${p.caught_ball_name}</td><td>${p.is_shiny?"是":"否"}</td><td>${p.current_hp}/${p.max_hp}</td><td>${moves}</td><td>${p.checksum_ok?"OK":"错误"}</td><td>${legalityBadge(p)}</td></tr>`;
  });
  document.getElementById("content").innerHTML = html + "</tbody></table>";
}
function renderBoxes() {
  const tabs = [["all", `全部 ${state.boxes.length}`], ...Array.from({length: 14}, (_, i) => {
    const box = String(i + 1);
    const s = (state.boxes_by_box || {})[box] || {filled: 0, total: 30};
    return [box, `${box}号盒 ${s.filled}/${s.total}`];
  })];
  const rows = state.boxes.filter(p => boxView === "all" || String(p.box) === boxView);
  document.getElementById("summary").textContent = `盒子：${state.boxes.length} 只非空宝可梦`;
  let html = "<table><thead><tr><th>盒子</th><th>格位</th><th>种族</th><th>等级</th><th>性格</th><th>性别</th><th>特性</th><th>球</th><th>闪光</th><th>携带</th><th>招式</th><th>数据校验</th><th>合法性</th></tr></thead><tbody>";
  rows.forEach((p) => {
    const i = state.boxes.indexOf(p);
    const held = p.held_item ? `${p.held_item} ${romLink("items", p.held_item, p.held_item_name)}` : "空";
    const moves = p.moves.map((id, idx) => romLink("moves", id, p.move_names[idx])).join(" / ");
    html += `<tr onclick="selectBox(${i})"><td>${p.box}</td><td>${p.box_slot}</td><td>${p.species} ${romLink("species", p.species, p.species_name)}</td><td>PC</td><td>${p.nature_name}</td><td>${p.gender}</td><td>${p.ability_id} ${romLink("abilities", p.ability_id, p.ability_name)}</td><td>${p.caught_ball_name}</td><td>${p.is_shiny?"是":"否"}</td><td>${held}</td><td>${moves}</td><td>${p.checksum_ok?"OK":"错误"}</td><td>${legalityBadge(p)}</td></tr>`;
  });
  document.getElementById("content").innerHTML = renderSubtabs(tabs, boxView, "setBoxView") + html + "</tbody></table>";
}
function setBoxView(next) { boxView = next; selected = null; renderBoxes(); }
function legalityBadge(p) {
  const rows = p.legality || [];
  const ok = rows.length === 1 && /合法性通过$/.test(rows[0]);
  if (ok) return "通过";
  return `<span class="bad">可疑 ${rows.length}</span>`;
}
async function selectParty(i) {
  const p = state.party[i];
  document.getElementById("detail").textContent = p.legality.join("\n");
  pokemonFormConstraints = await loadPokemonConstraints(p.species, p.level);
  renderPokemonForm(p, pokemonFormConstraints, "party");
}
function renderPokemonForm(p, constraints, location) {
  const isBox = location === "box";
  const constraintLevel = formConstraintLevel(p, location);
  document.getElementById("form").innerHTML = `
    <input type="hidden" id="location" value="${location}">
    ${isBox ? `<label>盒子<input id="box" value="${p.box}" readonly></label><label>格位<input id="box_slot" value="${p.box_slot}" readonly></label>` : field("slot","槽位",p.slot,true)}
    ${field("personality","PID",p.personality,true)}
    ${field("species","种族 ID",p.species,false,"species-list", "refreshPokemonConstraintsFromForm()")}
    ${field("held_item","携带道具 ID",p.held_item,false,"item-list")}
    ${natureField(p.nature_id)}
    ${genderField(p.gender, constraints)}
    ${abilityField(p.ability_bit, constraints)}
    <label>当前特性<input value="${p.ability_id} ${escapeHtml(p.ability_name)}" readonly></label>
    <label>捕获球<input value="${p.caught_ball} ${escapeHtml(p.caught_ball_name)}" readonly></label>
    ${shinyField(p.is_shiny)}
    ${field("experience","经验值",p.experience)}
    ${field("friendship","亲密度",p.friendship)}
    ${isBox ? field("constraint_level","约束等级",constraintLevel,false,"", "refreshPokemonConstraintsFromForm()") : field("level","当前等级",p.level,false,"", "refreshPokemonConstraintsFromForm()")}
    ${isBox ? "" : field("current_hp","当前 HP",p.current_hp)}
    <div id="move-controls">${moveFields(p.moves, p.pps, constraints)}</div>
    ${field("evs","努力值 HP/攻/防/速/特攻/特防",p.evs.join(","))}
    ${field("ivs","个体值 HP/攻/防/速/特攻/特防",p.ivs.join(","))}
    ${field("is_egg","蛋 0/1",p.is_egg ? 1 : 0)}
    <p><button type="button" class="primary" onclick="updatePokemon()">写入宝可梦</button></p>`;
}
async function selectBox(i) {
  const p = state.boxes[i];
  document.getElementById("detail").textContent = p.legality.join("\n");
  pokemonFormConstraints = await loadPokemonConstraints(p.species, formConstraintLevel(p, "box"));
  renderPokemonForm(p, pokemonFormConstraints, "box");
}
async function updatePokemon() {
  const location = val("location");
  const ids = ["location","species","held_item","nature_id","gender","is_shiny","experience","friendship","evs","ivs","ability_bit","is_egg"];
  const body = {};
  ids.forEach(id => body[id] = val(id));
  if (location === "box") {
    body.box = val("box");
    body.box_slot = val("box_slot");
  } else {
    body.slot = val("slot");
    body.level = val("level");
    body.current_hp = val("current_hp");
  }
  body.moves = [0,1,2,3].map(i => num(`move_${i}`));
  body.pps = [0,1,2,3].map(i => num(`pp_${i}`));
  const data = await request("/api/pokemon", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
  setStatus(data.message + "\n尚未保存到文件");
  await refresh();
}
function natureField(current) {
  const names = ["勤奋","怕寂寞","勇敢","固执","顽皮","大胆","坦率","悠闲","淘气","乐天","胆小","急躁","认真","爽朗","天真","内敛","慢吞吞","冷静","害羞","马虎","温和","温顺","自大","慎重","浮躁"];
  return `<label>性格<select id="nature_id">${names.map((name, id) => `<option value="${id}" ${id===current?"selected":""}>${id} ${name}</option>`).join("")}</select></label>`;
}
function genderField(current, constraints=null) {
  const values = constraints?.gender_options?.length ? constraints.gender_options : ["雄","雌","无性别"];
  return `<label>性别<select id="gender">${values.map(v => `<option value="${v}" ${v===current?"selected":""}>${v}</option>`).join("")}</select></label>`;
}
function abilityField(current, constraints=null) {
  const values = constraints?.ability_options?.length ? constraints.ability_options : [{bit:0, id:"", name:"特性位 0"}, {bit:1, id:"", name:"特性位 1"}];
  return `<label>特性<select id="ability_bit">${values.map(a => `<option value="${a.bit}" ${Number(a.bit)===Number(current)?"selected":""}>${a.bit} ${a.id ? a.id + " " : ""}${escapeHtml(a.name)}</option>`).join("")}</select></label>`;
}
function moveFields(moves, pps, constraints=null) {
  const options = buildMoveOptions(moves, constraints);
  return [0,1,2,3].map(i => `
    <div class="move-grid">
      <label>招式 ${i + 1}
        <select id="move_${i}" onchange="syncMovePp(${i})">
          ${options.map(o => `<option value="${o.id}" data-pp="${o.pp || 0}" ${o.disabled?"disabled":""} ${Number(o.id)===Number(moves[i])?"selected":""}>${escapeHtml(o.label)}</option>`).join("")}
        </select>
      </label>
      <label>PP<input id="pp_${i}" value="${pps[i] ?? 0}"></label>
    </div>`).join("");
}
function buildMoveOptions(currentMoves, constraints=null) {
  const seen = new Set();
  const rows = [{id:0, pp:0, label:"0 空", disabled:false}];
  seen.add(0);
  function add(id, name, pp, sources, disabled=false) {
    if (seen.has(Number(id))) return;
    seen.add(Number(id));
    const suffix = sources && sources.length ? ` [${sources.join("/")}]` : "";
    rows.push({id, pp, label:`${id} ${name}${suffix}`, disabled});
  }
  (constraints?.moves || []).forEach(m => add(m.id, m.name, m.pp, m.sources, false));
  (constraints?.future_moves || []).forEach(m => add(m.id, m.name, m.pp, m.sources, true));
  currentMoves.forEach(id => {
    if (!seen.has(Number(id))) {
      const row = (names?.moves || []).find(m => Number(m.id) === Number(id));
      add(id, row?.name || `招式 ${id}`, 0, ["当前"], false);
    }
  });
  return rows;
}
function syncMovePp(index) {
  const move = document.getElementById(`move_${index}`);
  const pp = document.getElementById(`pp_${index}`);
  const selected = move.options[move.selectedIndex];
  pp.value = selected?.dataset?.pp || 0;
}
async function loadPokemonConstraints(species, level) {
  try {
    return await request(`/api/pokemon_constraints?species=${encodeURIComponent(species)}&level=${encodeURIComponent(level)}`);
  } catch (error) {
    setStatus(error.message);
    return null;
  }
}
async function refreshPokemonConstraintsFromForm() {
  const species = num("species");
  const level = document.getElementById("constraint_level") ? num("constraint_level") : num("level");
  pokemonFormConstraints = await loadPokemonConstraints(species, level);
  const moves = [0,1,2,3].map(i => num(`move_${i}`));
  const pps = [0,1,2,3].map(i => num(`pp_${i}`));
  const currentGender = val("gender");
  const currentAbility = val("ability_bit");
  const genderWrapper = document.getElementById("gender").parentElement;
  const abilityWrapper = document.getElementById("ability_bit").parentElement;
  genderWrapper.outerHTML = genderField(currentGender, pokemonFormConstraints);
  abilityWrapper.outerHTML = abilityField(currentAbility, pokemonFormConstraints);
  document.getElementById("move-controls").innerHTML = moveFields(moves, pps, pokemonFormConstraints);
}
function formConstraintLevel(p, location) {
  if (location !== "box") return p.level || 1;
  return 100;
}
function shinyField(current) {
  return `<label>闪光<select id="is_shiny"><option value="0" ${current?"":"selected"}>否</option><option value="1" ${current?"selected":""}>是</option></select></label>`;
}
function renderNames() {
  if (!names) return;
  const stats = names.stats;
  const dictionaryTabs = [["all", "全部"], ["species", "宝可梦"], ["abilities", "特性"], ["moves", "招式"], ["items", "道具"]];
  if (!dictionaryTabs.some(([id]) => id === collectTable)) collectTable = "all";
  const rows = filteredNameRows();
  const dictionaryTabButtons = dictionaryTabs.map(([id, label]) => `<button class="${collectTable===id?"active":""}" onclick="setCollectTable('${escapeJsString(id)}')">${escapeHtml(label)}</button>`).join("");
  document.getElementById("summary").innerHTML =
    `<span>字典表：全部 ${names.rows.length} 条</span>
     <span class="summary-controls"><button type="button" onclick="reloadNames()">刷新码表</button></span>`;
  let html = `
    <div class="metrics">
      <div class="metric"><b>${stats.rom.species}</b>宝可梦枚举</div>
      <div class="metric"><b>${stats.rom.moves}</b>招式枚举</div>
      <div class="metric"><b>${stats.rom.abilities}</b>特性枚举</div>
      <div class="metric"><b>${stats.rom.items}</b>道具枚举</div>
      <div class="metric"><b>${stats.party_count}</b>队伍宝可梦</div>
      <div class="metric"><b>${stats.box_occupied}/${stats.box_slots}</b>盒子占用</div>
      <div class="metric"><b>${stats.bag_filled}/${stats.bag_slots}</b>背包占用</div>
      <div class="metric"><b>${stats.charmap.observed_keys}</b>存档引用字符码</div>
    </div>
    <div class="tabs subtabs dictionary-tabs">
      ${dictionaryTabButtons}
      <input value="${escapeHtml(collectSearch)}" onchange="setCollectSearch(this.value)" placeholder="按 ID、字码、当前值搜索">
      <span class="badge">当前 ${rows.length} 条</span>
    </div>
    <table><thead><tr><th>ID</th><th>字码</th><th>当前值</th><th>修改值</th><th>操作</th></tr></thead><tbody>`;
  rows.forEach(({r, idx}, viewIndex) => {
    const decoded = r.decoded || r.name || "";
    const unknown = r.unknown_count ? ` <span class="bad">${r.unknown_count}</span>` : "";
    const inputId = `name-${viewIndex}`;
    const selectedClass = selected && selected.table === r.table && selected.id === r.id ? "selected" : "";
    html += `<tr id="rom-${r.table}-${r.id}" class="${selectedClass}" onclick="selectNameIndex(${idx})"><td>${r.id}</td><td>${escapeHtml((r.tokens || []).join(" "))}</td><td>${escapeHtml(decoded)}${unknown}</td><td><input id="${inputId}" value="" placeholder="按游戏里看到的文字填写" onclick="event.stopPropagation();"></td><td><button type="button" onclick="saveNameCollected('${r.table}', ${r.id}, '${inputId}'); event.stopPropagation();">写入码表</button></td></tr>`;
  });
  html += "</tbody></table>";
  document.getElementById("content").innerHTML = html;
  document.getElementById("detail").textContent = "字典表来自 data/rom_text.json。字码是 ROM 文本编码单元，可能是 1 字节或 2 字节，不等同于半角/全角字符；填写完整显示名后会更新 character_map，并刷新其他 tab。";
}
function filteredNameRows() {
  const q = collectSearch.trim().toLowerCase();
  const rows = names.rows
    .map((r, idx) => ({r, idx}))
    .filter(({r}) => collectTable === "all" || r.table === collectTable)
    .filter(({r}) => !q || String(r.id).includes(q) || String(r.decoded || r.name || "").toLowerCase().includes(q) || (r.tokens || []).join(" ").toLowerCase().includes(q));
  return rows.map(row => ({...row, location: ""}));
}
function setCollectTable(next) { collectTable = next; renderNames(); }
function setCollectSearch(next) { collectSearch = next; renderNames(); }
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
  document.getElementById("detail").textContent = [
    `${table} #${id}`,
    `当前解码：${row.decoded || row.name || ""}`,
    `字符码：${(row.tokens || []).join(" ")}`,
  ].join("\n");
}
function selectNameIndex(idx) {
  const row = names.rows[idx];
  if (!row) return;
  selected = {table: row.table, id: row.id};
  document.getElementById("detail").textContent = [
    `${row.table_label} #${row.id}`,
    `当前解码：${row.decoded || row.name || ""}`,
    `字符码：${(row.tokens || []).join(" ")}`,
  ].join("\n");
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
async function saveNameCollected(table, id, inputId) {
  const row = nameRow(table, id);
  if (!row) return;
  const text = document.getElementById(inputId).value;
  const data = await request("/api/charmap", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({tokens: row.tokens, text})});
  setStatus(data.message + "\n" + Object.entries(data.updates).map(([k,v]) => `${k}=${v}`).join(" "));
  await refresh();
}
function field(id, label, value, readonly=false, list="", onchange="") { return `<label>${label}<input id="${id}" value="${value}" ${list?`list="${list}"`:""} ${readonly?"readonly":""} ${onchange?`onchange="${onchange}"`:""}></label>`; }
function val(id) { return document.getElementById(id).value; }
function num(id) { return parseInt(val(id), 10); }
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
