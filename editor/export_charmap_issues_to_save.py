#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pokemon_save_core import BOX_COUNT, BOX_SLOTS
from pokemon_save_core import EmeraldSave
from pokemon_save_core import ability_options_for_species, ability_id_for_species, set_rom_path
from rom_data import load_rom_text, save_rom_text, set_default_rom_path


TABLE_NAMES = {
    "species": "宝可梦",
    "moves": "招式",
    "abilities": "特性",
    "items": "道具",
}


@dataclass(frozen=True)
class PokemonRef:
    table: str
    id: int
    name: str
    decoded: str
    positions: list[int]


def find_matching_rom(save_path: Path) -> Path | None:
    # 支持输入 `xxx.sav.bak`，优先使用与 ROM 同名的文件名
    name = save_path.name.lower()
    if name.endswith(".sav.bak"):
        stem = save_path.name[:-8]
    else:
        stem = save_path.stem
    for suffix in (".gba", ".GBA"):
        candidate = save_path.with_name(f"{stem}{suffix}")
        if candidate.exists():
            return candidate
    return None


def build_species_by_ability() -> dict[int, list[tuple[int, int]]]:
    mapping: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for species_id in range(1, 1025):
        for ability_bit, ability_id in ability_options_for_species(species_id):
            mapping[ability_id].append((species_id, ability_bit))
    # 去重并保持 species_id 顺序稳定
    deduped: dict[int, list[tuple[int, int]]] = {}
    for ability_id, items in mapping.items():
        seen = set()
        values = []
        for entry in items:
            if entry in seen:
                continue
            seen.add(entry)
            values.append(entry)
        deduped[ability_id] = values
    return deduped


def _collect_focus_fields(refs: list[dict]) -> list[str]:
    focus: list[str] = []
    has = {ref.get("table") for ref in refs}
    if "宝可梦" in has:
        focus.append("species")
    if "特性" in has:
        focus.append("ability")
    if "道具" in has:
        focus.append("held_item")
    if "招式" in has:
        for _ in range(min(4, sum(1 for ref in refs if ref.get("table") == "招式"))):
            focus.append("move")
    return focus


def _select_species_for_ability(
    ability_ids: list[int],
    preferred_species: list[int],
    ability_to_species: dict[int, list[tuple[int, int]]],
    valid_species: set[int] | None = None,
) -> tuple[int | None, int | None, int | None]:
    for ability_id in ability_ids:
        candidates = ability_to_species.get(ability_id)
        if not candidates:
            continue
        for species_id, ability_bit in candidates:
            if species_id in preferred_species:
                if valid_species is None or species_id in valid_species:
                    return species_id, ability_bit, ability_id
        if valid_species:
            for species_id, ability_bit in candidates:
                if species_id in valid_species:
                    return species_id, ability_bit, ability_id
        for species_id, ability_bit in candidates:
            if species_id in preferred_species:
                return species_id, ability_bit, ability_id
        species_id, ability_bit = candidates[0]
        return species_id, ability_bit, ability_id
    return None, None, None


def collect_code_references(rom_data: dict) -> dict[str, list[PokemonRef]]:
    refs: dict[str, list[PokemonRef]] = defaultdict(list)
    for table in TABLE_NAMES:
        entries = rom_data.get(table, {})
        for raw_id, entry in sorted(entries.items(), key=lambda item: int(item[0])):
            item_id = int(raw_id)
            name = str(entry.get("name") or entry.get("decoded") or "")
            decoded = str(entry.get("decoded") or name or "")
            tokens = [str(token).upper() for token in (entry.get("tokens") or [])]
            pos_by_code: dict[str, list[int]] = defaultdict(list)
            for index, token in enumerate(tokens):
                pos_by_code[token].append(index)
            for code, positions in pos_by_code.items():
                if not code:
                    continue
                refs[code].append(PokemonRef(TABLE_NAMES[table], item_id, name, decoded, positions))
    return refs


def build_duplicate_char_groups(charmap: dict[str, str]) -> list[dict]:
    by_char: dict[str, list[str]] = defaultdict(list)
    for code, char in charmap.items():
        if char:
            by_char[char].append(code)
    groups: list[dict] = []
    for char, codes in by_char.items():
        codes_sorted = sorted(codes, key=str.upper)
        if len(codes_sorted) <= 1:
            continue
        groups.append({"char": char, "codes": codes_sorted})
    groups.sort(key=lambda g: (-len(g["codes"]), g["char"]))
    return groups


def build_issue_payloads(rom_data: dict, duplicates: list[dict], unresolved: Iterable[str], max_checkers_per_issue: int = 3) -> list[dict]:
    refs = collect_code_references(rom_data)
    issues: list[dict] = []

    for group in duplicates:
        char = group["char"]
        codes = group["codes"]
        selected = sorted(codes[:max_checkers_per_issue])
        issue_refs = []
        for code in selected:
            issue_refs.append(
                {
                    "code": code,
                    "references": [
                        {
                            "table": r.table,
                            "table_id": r.id,
                            "name": r.name,
                            "decoded": r.decoded,
                            "positions": r.positions,
                        }
                        for r in refs.get(code, [])
                    ],
                }
            )
        issues.append(
            {
                "type": "duplicate_char",
                "char": char,
                "codes": codes,
                "check_codes": selected,
                "references_by_code": issue_refs,
            }
        )

    for code in unresolved:
        issue_refs = [
            {
                "code": code,
                "references": [
                    {
                        "table": r.table,
                        "table_id": r.id,
                        "name": r.name,
                        "decoded": r.decoded,
                        "positions": r.positions,
                    }
                    for r in refs.get(code, [])
                ],
            }
        ]
        issues.append(
            {
                "type": "unverified_code",
                "char": rom_data.get("character_map", {}).get(code, ""),
                "codes": [code],
                "check_codes": [code],
                "references_by_code": issue_refs,
            }
        )

    return issues


def build_checker_updates(code: str, refs: list[dict], valid_species: set[int] | None = None) -> dict:
    # 默认落位到一个固定且稳定的种族，后续再按引用约束进行替换
    species_id = 25
    species_reason = "默认（未匹配到种族约束）"
    ability_bit: int | None = None
    ability_id: int | None = None
    ability_from_ref: int | None = None

    ability_to_species = build_species_by_ability()

    species_refs = [ref for ref in refs if ref.get("table") == "宝可梦"]
    ability_refs = [ref for ref in refs if ref.get("table") == "特性"]
    item_refs = [ref for ref in refs if ref.get("table") == "道具"]
    move_refs = [ref for ref in refs if ref.get("table") == "招式"]

    preferred_species = [int(ref.get("table_id", 0)) for ref in species_refs]
    preferred_species = [sid for sid in preferred_species if sid > 0]
    preferred_species = list(dict.fromkeys(preferred_species))

    ability_ids = []
    for ref in ability_refs:
        try:
            aid = int(ref.get("table_id"))
        except (TypeError, ValueError):
            continue
        if aid > 0 and aid not in ability_ids:
            ability_ids.append(aid)

    # 若有特性引用，必须通过“可拥有该特性的宝可梦”来放置，而不是直接改 ability_id
    if ability_ids:
        chosen_species_id, chosen_bit, chosen_ability_id = _select_species_for_ability(
            ability_ids,
            preferred_species,
            ability_to_species,
            valid_species,
        )
        if chosen_species_id is not None and chosen_bit is not None:
            species_id = chosen_species_id
            ability_bit = chosen_bit
            ability_id = chosen_ability_id
            ability_from_ref = chosen_ability_id
            species_reason = f"按特性表 {chosen_ability_id} 匹配"
        elif preferred_species:
            species_id = preferred_species[0]
            species_reason = "按特性匹配失败，回退到第一个引用种族"

    # 若无特性匹配成功，仍可优先使用引用里的种族作为种族标识
    if not ability_refs and preferred_species:
        species_id = preferred_species[0]
        species_reason = "按引用宝可梦"

    # 无特性时保留默认 species_id = 25，只要有可用 move/item 引用就照样放置对应字段
    held_item = 0
    move_ids: list[int] = []
    for ref in item_refs:
        rid = int(ref.get("table_id", 0))
        if held_item == 0 and rid > 0:
            held_item = rid

    for ref in move_refs:
        rid = int(ref.get("table_id", 0))
        if rid not in move_ids:
            move_ids.append(rid)

    if ability_id is not None and ability_id > 0:
        actual = ability_id_for_species(species_id, ability_bit or 0)
        if actual != ability_id:
            requested_ability_id = ability_id
            species_id = preferred_species[0] if preferred_species else species_id
            ability_bit = None
            ability_id = None
            ability_from_ref = None
            species_reason = f"特性 {requested_ability_id} 无法由当前种族派生，回退种族来源"

    while len(move_ids) < 4:
        move_ids.append(0)

    focus_fields = _collect_focus_fields(refs)
    if not focus_fields:
        focus_fields = ["species"]

    return {
        "species": species_id,
        "species_reason": species_reason,
        "held_item": held_item,
        "ability_bit": ability_bit,
        "ability_id": ability_id,
        "ability_from_ref": ability_from_ref,
        "moves": move_ids[:4],
        "focus_fields": focus_fields,
    }


def _box_slot_from_global(slot_index: int) -> tuple[int, int]:
    # slot_index 从 0 开始、基于整个盒子区域（1-14）排序
    box = slot_index // BOX_SLOTS + 1
    slot = slot_index % BOX_SLOTS + 1
    return box, slot


def write_validation_monsters(
    save_path: Path,
    output_path: Path,
    rom_data: dict,
    issues: list[dict],
    start_box: int = 3,
    checkers_per_issue: int = 3,
) -> dict:
    output_path.write_bytes(save_path.read_bytes())
    save = EmeraldSave(output_path)

    start_slot_index = (start_box - 1) * BOX_SLOTS
    valid_species = {int(sid) for sid in rom_data.get("species", {}).keys()}
    cursor = start_slot_index
    limit = BOX_COUNT * BOX_SLOTS
    planned_checks: list[dict] = []
    for issue in issues:
        for code_ref in issue["references_by_code"][:checkers_per_issue]:
            code = code_ref["code"]
            refs = code_ref["references"]
            if not isinstance(code_ref, dict):
                continue
            if cursor >= limit:
                raise RuntimeError("盒子起始槽位后可用空间不足，无法放下全部校验项")
            box, slot = _box_slot_from_global(cursor)
            cursor += 1
            updates = build_checker_updates(code, refs, valid_species=valid_species)
            update_payload = {
                "species": updates["species"],
                "held_item": updates["held_item"],
                "moves": updates["moves"],
            }
            if updates["ability_bit"] is not None:
                update_payload["ability_bit"] = updates["ability_bit"]
            pokemon = save.update_box_pokemon(box, slot, update_payload)
            planned_checks.append(
                {
                    "issue_type": issue["type"],
                    "char": issue.get("char"),
                    "code": code,
                    "box": box,
                    "box_slot": slot,
                    "species_id": pokemon.species,
                    "species_reason": updates["species_reason"],
                    "focus_fields": updates["focus_fields"],
                    "held_item": pokemon.held_item,
                    "moves": updates["moves"],
                    "reference_count": len(refs),
                    "references": refs,
                    "species_name": pokemon.species_name,
                    "held_item_name": pokemon.held_item_name,
                    "move_names": [lookup_entry_name(rom_data, "moves", move_id) for move_id in updates["moves"]],
                    "ability_bit": updates["ability_bit"],
                    "ability_id": pokemon.ability_id if updates["ability_bit"] is not None else updates["ability_id"],
                    "ability_from_ref": updates["ability_from_ref"],
                    "ability_name": pokemon.ability_name if updates["ability_bit"] is not None else None,
                }
            )

    output_path.write_bytes(bytes(save.data))
    return {"save_path": str(output_path), "placed_checks": planned_checks, "next_box": _box_slot_from_global(cursor)[0] if cursor < limit else BOX_COUNT}


def _format_ref_label(ref: dict) -> str:
    table = ref.get("table", "")
    name = str(ref.get("name") or "").strip()
    rid = ref.get("table_id", "")
    id_text = f"{rid}" if rid != "" else ""
    positions = ref.get("positions", [])
    if positions:
        pos_text = f" (位置: {','.join(str(i + 1) for i in positions)})"
    else:
        pos_text = ""
    if id_text:
        return f"{table} {id_text} {name}{pos_text}".strip()
    return f"{table} {name}{pos_text}".strip()


def lookup_entry_name(rom_data: dict, table: str, item_id: int) -> str:
    table_data = rom_data.get(table, {})
    entry = table_data.get(str(item_id), {})
    return str(entry.get("name") or entry.get("decoded") or "")


def build_human_report(
    report_payload: dict,
    write_plan: list[dict],
    duplicate_groups: list[dict],
    unresolved_codes: list[dict],
) -> str:
    lines: list[str] = []
    lines.append("# 码表校验清单")
    lines.append("")
    lines.append(f"输入存档: `{report_payload['input_backup']}`")
    lines.append(f"输出存档: `{report_payload['output_sav']}`")
    lines.append(f"同名 ROM: `{report_payload['rom_path']}`")
    lines.append(f"起始盒子: {report_payload['start_box']}")
    lines.append(f"每组最大放置数量: {report_payload['max_checkers']}")
    lines.append(f"重复字符组: {len(duplicate_groups)}")
    lines.append(f"未核验码: {len(unresolved_codes)}")
    lines.append(f"总校验项: {len(write_plan)}")
    lines.append("")

    lines.append("## 1) 重复字符/未核验码汇总")
    lines.append("")
    for item in duplicate_groups:
        codes = ", ".join(item["codes"])
        lines.append(f"- 字符 `{item['char']}` 对应码值: {codes}")
    if unresolved_codes:
        lines.append("")
        lines.append("未核验码:")
        for item in unresolved_codes:
            lines.append(f"- `{item['code']}` ({item.get('char','')})")
    lines.append("")

    lines.append("## 2) 分组核验任务（按顺序，1组可能有2-3只）")
    lines.append("")
    field_label_map = {
        "species": "种族",
        "held_item": "道具",
        "ability": "特性",
        "move": "招式1-4",
    }

    def _format_focus(item: dict) -> list[str]:
        labels: list[str] = []
        focus_fields = item.get("focus_fields", [])
        for field in focus_fields:
            labels.append(field_label_map.get(field, str(field)))
        return list(dict.fromkeys(labels))

    grouped_items: dict[str, list[dict]] = defaultdict(list)
    for item in write_plan:
        # 以汉字分组，未核验码用码值兜底
        char = str(item.get("char") or "").strip()
        if char:
            grouped_items[f"char:{char}"].append(item)
        else:
            grouped_items[f"unverified:{item.get('code')}"].append(item)

    # 先按重复字符顺序输出，再输出未核验码顺序
    ordered_groups: list[tuple[str, str]] = []
    for group in duplicate_groups:
        ordered_groups.append((f"char:{group['char']}", f"字符 `{group['char']}`"))
    for unresolved in unresolved_codes:
        code = unresolved.get("code", "")
        ordered_groups.append((f"unverified:{code}", f"未核验码 `{code}`"))

    for idx, (group_key, title) in enumerate(ordered_groups, start=1):
        items = grouped_items.get(group_key, [])
        if not items:
            continue
        codes = [str(item.get("code", "")) for item in items]
        lines.append(f"### 组{idx}: {title}")
        lines.append(f"- 涉及码值: {', '.join(codes)}")
        for item in items:
            code = item.get("code", "")
            slot = f"{item['box']:02d}-{item['box_slot']:02d}"
            labels = _format_focus(item)
            lines.append(f"- 盒子 {slot}（码 {code}）")
            lines.append(f"  - 核验字段: {' / '.join(labels) if labels else '种族'}")
            detail_parts: list[str] = []
            if "species" in item.get("focus_fields", []):
                detail_parts.append(f"{item.get('species_name','')}({item.get('species_id',0)})")
            if "held_item" in item.get("focus_fields", []):
                detail_parts.append(f"{item.get('held_item_name','空')}")
            if "ability" in item.get("focus_fields", []):
                ability_name = item.get("ability_name") or "（未匹配）"
                detail_parts.append(f"{ability_name}")
            for idx_move, move_name in enumerate(item.get("move_names", [])[:4]):
                if "move" in item.get("focus_fields", []):
                    detail_parts.append(f"招式{idx_move + 1}={move_name or '空'}")
            if detail_parts:
                lines.append("  - 放置值: " + " / ".join(detail_parts))
            refs = [_format_ref_label(ref) for ref in item.get("references", [])[:4]]
            if refs:
                lines.append("  - 参考来源（前4条）: " + "；".join(refs))
        lines.append("")

    lines.append("")
    lines.append("## 3) 快速核验建议")
    lines.append("")
    lines.append("- 先打开存档，定位到第 3 盒开始。每个组看完再到下一个组。")
    lines.append("- 每条任务只看它对应的“核验字段”；“放置值”用于快速对照，不必逐条读完整来源。")
    lines.append("- 特性字段请通过特性文本核验，避免误以为能直接写入特性ID。")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="导出码表重复/未核验字符，并以它们为基准重建一个 .sav",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("backup_path", help="输入 .sav.bak 文件")
    parser.add_argument(
        "--start-box",
        type=int,
        default=3,
        help="从哪个盒子开始放置校验宝可梦（1~14）",
    )
    parser.add_argument(
        "--max-checkers",
        type=int,
        choices=[1, 2, 3],
        default=3,
        help="每个字符组放置多少个校验项（最多3）",
    )
    parser.add_argument(
        "--report-path",
        default=None,
        help="导出报告文件路径（默认跟随 .sav 输出为 *_validation_report.json）",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    backup_path = Path(args.backup_path).expanduser()
    if not backup_path.exists():
        raise FileNotFoundError(f"未找到输入文件: {backup_path}")
    if args.start_box < 1 or args.start_box > BOX_COUNT:
        raise ValueError(f"start_box 必须在 1~{BOX_COUNT} 之间")

    rom_path = find_matching_rom(backup_path)
    if rom_path is None:
        # 允许继续执行，但提示用户这会使用现有 data/rom_text.json 缓存
        print("未找到同名 ROM，使用 data/rom_text.json 现有版本")
        rom_data = load_rom_text()
    else:
        set_default_rom_path(rom_path)
        set_rom_path(rom_path)
        rom_data = load_rom_text()

    charmap = rom_data.get("character_map", {})
    unresolved_codes = rom_data.get("unresolved_character_codes", [])
    duplicate_groups = build_duplicate_char_groups(charmap)

    issues = build_issue_payloads(rom_data, duplicate_groups, unresolved_codes, args.max_checkers)
    print(f"重复字符组: {len(duplicate_groups)}")
    print(f"未核验码: {len(unresolved_codes)}")
    print(f"待放置校验项: {sum(len(i['check_codes']) for i in issues)}（max_checkers={args.max_checkers}）")

    if rom_path is None:
        output_sav = backup_path.with_suffix(".sav")
    else:
        output_sav = rom_path.with_suffix(".sav")

    result = write_validation_monsters(
        backup_path,
        output_sav,
        rom_data,
        issues=issues,
        start_box=args.start_box,
        checkers_per_issue=args.max_checkers,
    )

    if args.report_path is None:
        report_path = output_sav.with_name(f"{output_sav.stem}_validation_report.json")
    else:
        report_path = Path(args.report_path).expanduser()
    report_payload = {
        "input_backup": str(backup_path),
        "rom_path": str(rom_path) if rom_path else "",
        "output_sav": str(output_sav),
        "start_box": args.start_box,
        "max_checkers": args.max_checkers,
        "duplicate_groups": [
            {
                "char": item["char"],
                "codes": item["codes"],
            }
            for item in duplicate_groups
        ],
        "unverified_codes": [
            {"code": code, "char": charmap.get(code, ""), "references": []}
            for code in unresolved_codes
        ],
        "issues": issues,
        "write_plan": result["placed_checks"],
    }
    all_refs = collect_code_references(rom_data)
    # 将 dataclass 转 dict，避免 JSON 无法序列化
    for issue in report_payload["unverified_codes"]:
        issue["references"] = [
            {
                "table": r.table,
                "table_id": r.id,
                "name": r.name,
                "decoded": r.decoded,
                "positions": r.positions,
            }
            for r in all_refs.get(issue["code"], [])
        ]

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_text = build_human_report(
        report_payload,
        write_plan=result["placed_checks"],
        duplicate_groups=report_payload["duplicate_groups"],
        unresolved_codes=report_payload["unverified_codes"],
    )
    if report_path.suffix.lower() == ".json":
        md_path = report_path.with_suffix(".md")
    else:
        md_path = report_path.with_name(f"{report_path.name}.md")
    md_path.write_text(report_text, encoding="utf-8")

    print(f"已导出JSON报告: {report_path}")
    print(f"已导出可读报告: {md_path}")
    print(f"已生成 .sav: {output_sav}")
    print(f"实际放置校验项: {len(result['placed_checks'])}")
    print(f"起始/下一个可用盒子: {args.start_box} / {result['next_box']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
