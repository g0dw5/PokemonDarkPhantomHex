from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


DEFAULT_ROM: Path | None = None
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "rom_text.json"

SPECIES_NAMES_OFFSET = 0x3185C8
SPECIES_NAME_SIZE = 11
SPECIES_COUNT = 412

MOVE_NAMES_OFFSET = 0x31977C
MOVE_NAMES_EXT_OFFSET = 0x1903207
MOVE_EXT_START = 355
MOVE_NAME_SIZE = 13
MOVE_COUNT = 472

ABILITY_NAMES_OFFSET = 0x31B6DB
ABILITY_NAMES_EXT_OFFSET = 0x1C00000
ABILITY_EXT_START = 78
ABILITY_NAME_SIZE = 13
ABILITY_COUNT = 151

ITEMS_OFFSET = 0x5839A0
ITEM_ENTRY_SIZE = 44
ITEM_NAME_SIZE = 14
ITEM_COUNT = 377


@dataclass(frozen=True)
class TableSpec:
    key: str
    offset: int
    record_size: int
    name_size: int
    count: int
    ext_offset: int | None = None
    ext_start: int | None = None


TABLES = [
    TableSpec("species", SPECIES_NAMES_OFFSET, SPECIES_NAME_SIZE, SPECIES_NAME_SIZE, SPECIES_COUNT),
    TableSpec("moves", MOVE_NAMES_OFFSET, MOVE_NAME_SIZE, MOVE_NAME_SIZE, MOVE_COUNT, MOVE_NAMES_EXT_OFFSET, MOVE_EXT_START),
    TableSpec("abilities", ABILITY_NAMES_OFFSET, ABILITY_NAME_SIZE, ABILITY_NAME_SIZE, ABILITY_COUNT, ABILITY_NAMES_EXT_OFFSET, ABILITY_EXT_START),
    TableSpec("items", ITEMS_OFFSET, ITEM_ENTRY_SIZE, ITEM_NAME_SIZE, ITEM_COUNT),
]

TEXT_TERMINATOR = 0xFF
TEXT_PADDING = 0x00
CONTROL_TOKENS = {
    0xFC: "{CTRL_FC}",
    0xFD: "{VAR_FD}",
    0xFE: "\n",
}
CHARMAP_OUTPUT = OUTPUT


def load_charmap(path: Path = CHARMAP_OUTPUT) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(data, dict) and isinstance(data.get("character_map"), dict):
        data = data["character_map"]
    result: dict[str, str] = {}
    for key, value in data.items():
        code = str(key).upper()
        char = str(value)
        if code and char:
            result[code] = char
    return result


def save_charmap(updates: dict[str, str], path: Path = CHARMAP_OUTPUT) -> dict[str, str]:
    data = load_charmap(path)
    for key, value in updates.items():
        code = str(key).upper()
        char = str(value)
        if code and char:
            data[code] = char
    if path == CHARMAP_OUTPUT:
        save_rom_text(charmap=dict(sorted(data.items())))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(sorted(data.items())), ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def raw_name(rom: bytes, spec: TableSpec, index: int) -> bytes:
    if spec.ext_offset is not None and spec.ext_start is not None and index >= spec.ext_start:
        start = spec.ext_offset + (index - spec.ext_start) * spec.record_size
    else:
        start = spec.offset + index * spec.record_size
    return rom[start : start + spec.name_size]


def single_byte_text_codes(charmap: dict[str, str] | None = None) -> set[int]:
    if charmap is None:
        charmap = load_charmap()
    result: set[int] = set()
    for code, char in charmap.items():
        if len(code) != 2 or not char:
            continue
        try:
            result.add(int(code, 16))
        except ValueError:
            continue
    return result


def tokenize_name(raw: bytes, charmap: dict[str, str] | None = None) -> list[bytes]:
    tokens: list[bytes] = []
    single_byte_codes = single_byte_text_codes(charmap)
    i = 0
    while i < len(raw):
        byte = raw[i]
        if byte == TEXT_TERMINATOR:
            break
        if byte == TEXT_PADDING:
            i += 1
            continue
        if byte in CONTROL_TOKENS:
            tokens.append(bytes([byte]))
            i += 1
            continue
        if i + 1 < len(raw) and raw[i + 1] not in (TEXT_PADDING, TEXT_TERMINATOR, *CONTROL_TOKENS):
            pair = raw[i : i + 2]
            if pair.hex().upper() in charmap:
                tokens.append(pair)
                i += 2
                continue
            if byte < 0x20 and raw[i + 1] < 0x80:
                tokens.append(pair)
                i += 2
                continue
        if byte in single_byte_codes:
            tokens.append(bytes([byte]))
            i += 1
            continue
        if 0x20 <= byte <= 0x7E:
            tokens.append(bytes([byte]))
            i += 1
            continue
        if i + 1 < len(raw) and raw[i + 1] not in (TEXT_PADDING, TEXT_TERMINATOR, *CONTROL_TOKENS):
            tokens.append(raw[i : i + 2])
            i += 2
        else:
            tokens.append(bytes([byte]))
            i += 1
    return tokens


def gb2312_row_col(char: str) -> tuple[int, int] | None:
    try:
        encoded = char.encode("gb2312")
    except UnicodeEncodeError:
        return None
    if len(encoded) != 2:
        return None
    row = encoded[0] - 0xA0
    col = encoded[1] - 0xA0
    if 1 <= row <= 87 and 1 <= col <= 94:
        return row, col
    return None


def infer_gb2312_row_bases(seed_map: dict[str, str]) -> dict[int, int]:
    votes: dict[int, dict[int, int]] = {}
    for code, char in seed_map.items():
        if len(char) != 1:
            continue
        row_col = gb2312_row_col(char)
        if not row_col:
            continue
        row, col = row_col
        base = int(code, 16) - (col - 1)
        votes.setdefault(row, {})
        votes[row][base] = votes[row].get(base, 0) + 1
    result: dict[int, int] = {}
    for row, row_votes in votes.items():
        base, count = max(row_votes.items(), key=lambda item: item[1])
        if count >= 2:
            result[row] = base
    return result


def build_gb2312_inferred_map(seed_map: dict[str, str]) -> tuple[dict[str, str], dict[str, int]]:
    row_bases = infer_gb2312_row_bases(seed_map)
    inferred: dict[str, str] = {}
    for row, base in row_bases.items():
        for col in range(1, 95):
            code = f"{base + col - 1:04X}"
            if code in seed_map:
                continue
            try:
                inferred[code] = bytes([row + 0xA0, col + 0xA0]).decode("gb2312")
            except UnicodeDecodeError:
                continue
    return inferred, {f"{row:02d}": base for row, base in sorted(row_bases.items())}


def build_charmaps() -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, int]]:
    charmap = load_charmap()
    sources = {}
    inferred_map, row_bases = build_gb2312_inferred_map(charmap)
    candidate_map = dict(charmap)
    for code, char in inferred_map.items():
        if code not in candidate_map:
            candidate_map[code] = char
    return dict(sorted(charmap.items())), dict(sorted(candidate_map.items())), dict(sorted(sources.items())), row_bases


def collect_observed_char_codes(rom: bytes, charmap: dict[str, str]) -> set[str]:
    codes: set[str] = set()
    for spec in TABLES:
        for index in range(spec.count):
            raw = raw_name(rom, spec, index)
            codes.update(token.hex().upper() for token in tokenize_name(raw, charmap))
    return codes


def collect_rom_used_charmap_keys(rom: bytes, charmap: dict[str, str]) -> dict:
    by_code: dict[str, dict] = {}
    for spec in TABLES:
        for index in range(spec.count):
            raw = raw_name(rom, spec, index)
            tokens = tokenize_name(raw, charmap)
            decoded = decode_tokens(tokens, charmap)
            token_hex = [token.hex().upper() for token in tokens]
            for token_index, code in enumerate(token_hex):
                entry = by_code.setdefault(
                    code,
                    {
                        "code": code,
                        "char": charmap.get(code, ""),
                        "known": code in charmap,
                        "references": [],
                    },
                )
                entry["references"].append(
                    {
                        "table": spec.key,
                        "id": index,
                        "decoded": decoded,
                        "token_index": token_index,
                        "tokens": token_hex,
                    }
                )
    keys = sorted(by_code.values(), key=lambda item: (item["known"], item["code"]))
    payload = {
        "table_count": {spec.key: spec.count for spec in TABLES},
        "key_count": len(keys),
        "unknown_key_count": sum(1 for item in keys if not item["known"]),
        "keys": keys,
    }
    return payload


def decode_tokens(tokens: list[bytes], charmap: dict[str, str]) -> str:
    chars = []
    for token in tokens:
        key = token.hex().upper()
        if key in charmap:
            chars.append(charmap[key])
        elif len(token) == 1 and token[0] in CONTROL_TOKENS:
            chars.append(CONTROL_TOKENS[token[0]])
        elif len(token) == 1 and 0x20 <= token[0] <= 0x7E:
            chars.append(chr(token[0]))
        else:
            chars.append("{" + key.upper() + "}")
    return "".join(chars)


def extract_table(rom: bytes, spec: TableSpec, charmap: dict[str, str]) -> dict[str, dict[str, str | int]]:
    table: dict[str, dict[str, str | int]] = {}
    for index in range(spec.count):
        raw = raw_name(rom, spec, index)
        tokens = tokenize_name(raw, charmap)
        token_hex = [token.hex().upper() for token in tokens]
        decoded = decode_tokens(tokens, charmap)
        table[str(index)] = {
            "id": index,
            "name": decoded,
            "decoded": decoded,
            "tokens": token_hex,
        }
    return table


def require_rom_path(rom_path: Path | None = DEFAULT_ROM) -> Path:
    if rom_path is None:
        raise ValueError("未找到 ROM 文件，请将同名 .gba 放在存档同目录")
    return rom_path


def set_default_rom_path(path: Path | str | None) -> None:
    global DEFAULT_ROM
    DEFAULT_ROM = Path(path).expanduser() if path else None


def extract_rom_text(rom_path: Path | None = DEFAULT_ROM) -> dict:
    if rom_path is None:
        rom_path = DEFAULT_ROM
    rom_path = require_rom_path(rom_path)
    rom = rom_path.read_bytes()
    charmap, candidate_charmap, _char_sources, gb2312_row_bases = build_charmaps()
    observed_codes = collect_observed_char_codes(rom, charmap)
    character_map_all = {code: charmap.get(code, "") for code in sorted(observed_codes)}
    candidate_character_map_all = {code: candidate_charmap.get(code, "") for code in sorted(observed_codes)}
    tables = {spec.key: extract_table(rom, spec, charmap) for spec in TABLES}
    used_keys = collect_rom_used_charmap_keys(rom, charmap)
    return {
        "rom": str(rom_path),
        "character_map": charmap,
        "tables": {
            spec.key: {
                "offset": spec.offset,
                "record_size": spec.record_size,
                "name_size": spec.name_size,
                "count": spec.count,
                "ext_offset": spec.ext_offset,
                "ext_start": spec.ext_start,
            }
            for spec in TABLES
        },
        "character_map_count": len(charmap),
        "gb2312_row_bases": gb2312_row_bases,
        "rom_used_character_key_count": used_keys["key_count"],
        "rom_unknown_character_key_count": used_keys["unknown_key_count"],
        "used_character_keys": used_keys["keys"],
        "unresolved_character_codes": [code for code, char in character_map_all.items() if not char],
        "candidate_unresolved_character_codes": [code for code, char in candidate_character_map_all.items() if not char],
        "text_model": {
            "terminator": f"{TEXT_TERMINATOR:02X}",
            "padding": f"{TEXT_PADDING:02X}",
            "controls": {f"{key:02X}": value for key, value in CONTROL_TOKENS.items()},
            "token_policy": "main decode uses data/rom_text.json character_map; gb2312 row inference is exported as candidates only",
        },
        **tables,
    }


def save_rom_text(rom_path: Path | None = DEFAULT_ROM, output: Path = OUTPUT, charmap: dict[str, str] | None = None) -> dict:
    if rom_path is None:
        rom_path = DEFAULT_ROM
    rom_path = require_rom_path(rom_path)
    if charmap is None:
        charmap = load_charmap(output)
    rom = rom_path.read_bytes()
    _charmap, candidate_charmap, _char_sources, gb2312_row_bases = build_charmaps()
    if charmap:
        _charmap = dict(sorted(charmap.items()))
        inferred_map, gb2312_row_bases = build_gb2312_inferred_map(_charmap)
        candidate_charmap = dict(_charmap)
        for code, char in inferred_map.items():
            candidate_charmap.setdefault(code, char)
    observed_codes = collect_observed_char_codes(rom, _charmap)
    character_map_all = {code: _charmap.get(code, "") for code in sorted(observed_codes)}
    candidate_character_map_all = {code: candidate_charmap.get(code, "") for code in sorted(observed_codes)}
    used_keys = collect_rom_used_charmap_keys(rom, _charmap)
    data = {
        "rom": str(rom_path),
        "character_map": dict(sorted(_charmap.items())),
        "character_map_count": len(_charmap),
        "tables": {
            spec.key: {
                "offset": spec.offset,
                "record_size": spec.record_size,
                "name_size": spec.name_size,
                "count": spec.count,
                "ext_offset": spec.ext_offset,
                "ext_start": spec.ext_start,
            }
            for spec in TABLES
        },
        "gb2312_row_bases": gb2312_row_bases,
        "rom_used_character_key_count": used_keys["key_count"],
        "rom_unknown_character_key_count": used_keys["unknown_key_count"],
        "used_character_keys": used_keys["keys"],
        "unresolved_character_codes": [code for code, char in character_map_all.items() if not char],
        "candidate_unresolved_character_codes": [code for code, char in candidate_character_map_all.items() if not char],
        "text_model": {
            "terminator": f"{TEXT_TERMINATOR:02X}",
            "padding": f"{TEXT_PADDING:02X}",
            "controls": {f"{key:02X}": value for key, value in CONTROL_TOKENS.items()},
            "token_policy": "main decode uses data/rom_text.json character_map; gb2312 row inference is exported as candidates only",
        },
        **{spec.key: extract_table(rom, spec, _charmap) for spec in TABLES},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return data


def load_rom_text() -> dict:
    if not OUTPUT.exists():
        return save_rom_text()
    return json.loads(OUTPUT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    data = save_rom_text()
    print(f"写入 {OUTPUT}")
    print(f"字码映射：{data['character_map_count']} 个")
    print(f"ROM 引用字符码：{data['rom_used_character_key_count']} 个，未映射 {data['rom_unknown_character_key_count']} 个")
    for key in ("species", "moves", "abilities", "items"):
        print(f"{key}: {len(data[key])} 条")
