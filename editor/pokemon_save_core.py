from __future__ import annotations

import shutil
import struct
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterable


SECTION_SIZE = 0x1000
SAVE_BLOCK_SIZE = 14 * SECTION_SIZE
SIGNATURE = 0x08012025

SECTION_CHECKSUM_SIZES = {
    0: 3884,
    1: 3968,
    2: 3968,
    3: 3968,
    4: 3848,
    5: 3968,
    6: 3968,
    7: 3968,
    8: 3968,
    9: 3968,
    10: 3968,
    11: 3968,
    12: 3968,
    13: 2000,
}

PARTY_COUNT_OFFSET = 0x0234
PARTY_OFFSET = 0x0238
PARTY_SIZE = 100
BOX_COUNT = 14
BOX_SLOTS = 30
BOX_POKEMON_SIZE = 80
BOX_DATA_SIZE = BOX_COUNT * BOX_SLOTS * BOX_POKEMON_SIZE
BOX_DATA_OFFSET = 4
BOX_SECTION_IDS = range(5, 14)

SECURITY_KEY_OFFSET = 0x00AC
SECURITY_KEY_COPY_OFFSET = 0x01F4
TRAINER_NAME_OFFSET = 0x0000
TRAINER_NAME_SIZE = 7
TRAINER_GENDER_OFFSET = 0x0008
TRAINER_ID_OFFSET = 0x000A
SECRET_ID_OFFSET = 0x000C
PLAY_TIME_HOURS_OFFSET = 0x000E
PLAY_TIME_MINUTES_OFFSET = 0x0010
PLAY_TIME_SECONDS_OFFSET = 0x0011
PLAY_TIME_FRAMES_OFFSET = 0x0012
MONEY_OFFSET = 0x0490
COINS_OFFSET = 0x0494
ROM_PATH: Path | None = None
BASE_STATS_OFFSET = 0x3203CC
BASE_STATS_SIZE = 28
BASE_STATS_GROWTH_RATE_OFFSET = 19
ROM_SPECIES_COUNT = 412
ROM_MOVE_COUNT = 472
MOVE_DATA_OFFSET = 0x1900000
MOVE_DATA_SIZE = 12
MOVE_PP_OFFSET = 4
LEVEL_UP_LEARNSET_POINTERS_OFFSET = 0x329378
LEVEL_UP_LEARNSET_SPECIES_OFFSET = 1
EVOLUTIONS_OFFSET = 0x32531C
EVOLUTION_ENTRY_SIZE = 8
EVOLUTIONS_PER_SPECIES = 5
EVOLUTION_RECORD_SIZE = EVOLUTION_ENTRY_SIZE * EVOLUTIONS_PER_SPECIES
EGG_MOVES_OFFSET = 0x32ADD8
EGG_MOVE_SPECIES_MARKER_BASE = 20000
TMHM_COMPATIBILITY_OFFSET = 0x31E898
TMHM_COMPATIBILITY_SIZE = 8
TMHM_MOVES_OFFSET = 0x1CA0000
TMHM_COUNT = 58
TUTOR_MOVES_OFFSET = 0x61500C
TUTOR_COMPATIBILITY_OFFSET = 0x615048
TUTOR_COMPATIBILITY_SIZE = 4
TMHM_FIRST_ITEM_ID = 0x121
TMHM_LAST_ITEM_ID = TMHM_FIRST_ITEM_ID + TMHM_COUNT - 1
GBA_ROM_POINTER_BASE = 0x08000000

BAG_POCKETS = {
    "电脑道具": (0x0498, 50, False),
    "普通道具": (0x0560, 30, True),
    "重要道具": (0x05D8, 30, True),
    "精灵球": (0x0650, 16, True),
    "招式机/秘传机": (0x0690, 64, True),
    "树果": (0x0790, 46, True),
}

SUBSTRUCT_ORDERS = [
    "GAEM",
    "GAME",
    "GEAM",
    "GEMA",
    "GMAE",
    "GMEA",
    "AGEM",
    "AGME",
    "AEGM",
    "AEMG",
    "AMGE",
    "AMEG",
    "EGAM",
    "EGMA",
    "EAGM",
    "EAMG",
    "EMGA",
    "EMAG",
    "MGAE",
    "MGEA",
    "MAGE",
    "MAEG",
    "MEGA",
    "MEAG",
]

SPECIES_NAMES = {
    0: "空",
    1: "妙蛙种子",
    2: "妙蛙草",
    3: "妙蛙花",
    4: "小火龙",
    5: "火恐龙",
    6: "喷火龙",
    7: "杰尼龟",
    8: "卡咪龟",
    9: "水箭龟",
    25: "皮卡丘",
    26: "雷丘",
    129: "鲤鱼王",
    130: "暴鲤龙",
    133: "伊布",
    143: "卡比兽",
    150: "超梦",
    151: "梦幻",
    252: "木守宫",
    255: "火稚鸡",
    258: "水跃鱼",
    277: "大王燕",
    280: "拉鲁拉丝",
    281: "奇鲁莉安",
    282: "沙奈朵",
    287: "懒人獭",
    289: "请假王",
    298: "露力丽",
    304: "可可多拉",
    330: "沙漠蜻蜓",
    334: "七夕青鸟",
    350: "美纳斯",
    359: "阿勃梭鲁",
    371: "宝贝龙",
    372: "甲壳龙",
    373: "暴飞龙",
    374: "铁哑铃",
    375: "金属怪",
    376: "巨金怪",
    380: "拉帝亚斯",
    381: "拉帝欧斯",
    382: "盖欧卡",
    383: "固拉多",
    384: "烈空坐",
    385: "基拉祈",
    386: "代欧奇希斯",
}

ITEM_NAMES = {
    0: "空",
    1: "大师球",
    2: "高级球",
    3: "超级球",
    4: "精灵球",
    5: "狩猎球",
    13: "伤药",
    14: "解毒药",
    17: "灼伤药",
    18: "冰冻药",
    19: "解眠药",
    20: "解麻药",
    21: "全复药",
    22: "全满药",
    23: "厉害伤药",
    24: "好伤药",
    25: "万灵药",
    26: "活力碎片",
    27: "活力块",
    63: "速度强化",
    73: "PP提升剂",
    74: "PP最大剂",
    75: "釜炎仙贝",
    83: "火之石",
    84: "雷之石",
    85: "水之石",
    92: "心之鳞片",
    103: "自行车",
    113: "学习装置",
    179: "红色碎片",
    180: "蓝色碎片",
    181: "黄色碎片",
    182: "绿色碎片",
    183: "HP增强剂",
    184: "攻击增强剂",
    185: "防御增强剂",
    186: "速度增强剂",
    187: "特攻增强剂",
    188: "特防增强剂",
    189: "神奇糖果",
    196: "剩饭",
    202: "轻粉",
    213: "先制之爪",
    219: "龙之鳞片",
    230: "硬石头",
    231: "奇迹种子",
    232: "黑色眼镜",
    233: "黑带",
    234: "磁铁",
    235: "神秘水滴",
    236: "锐利鸟嘴",
    237: "毒针",
    238: "不融冰",
    239: "诅咒之符",
    240: "弯曲的汤匙",
    241: "木炭",
    242: "龙之牙",
    243: "丝绸围巾",
    244: "升级数据",
    245: "贝壳之铃",
    275: "力量头巾",
    276: "博识眼镜",
    277: "达人带",
    349: "TM01",
    350: "TM02",
    398: "TM50",
    399: "HM01",
    400: "HM02",
    401: "HM03",
    402: "HM04",
    403: "HM05",
    404: "HM06",
    405: "HM07",
    406: "HM08",
}

MOVE_NAMES: dict[int, str] = {}
ABILITY_NAMES: dict[int, str] = {}
BALL_NAMES = {
    0: "未知",
    1: "大师球",
    2: "高级球",
    3: "超级球",
    4: "精灵球",
    5: "狩猎球",
    6: "捕网球",
    7: "潜水球",
    8: "巢穴球",
    9: "重复球",
    10: "计时球",
    11: "豪华球",
    12: "纪念球",
}

NATURE_NAMES = [
    "勤奋",
    "怕寂寞",
    "勇敢",
    "固执",
    "顽皮",
    "大胆",
    "坦率",
    "悠闲",
    "淘气",
    "乐天",
    "胆小",
    "急躁",
    "认真",
    "爽朗",
    "天真",
    "内敛",
    "慢吞吞",
    "冷静",
    "害羞",
    "马虎",
    "温和",
    "温顺",
    "自大",
    "慎重",
    "浮躁",
]


def _extract_rom_dictionary() -> dict:
    if ROM_PATH is None:
        return {}
    try:
        from rom_data import extract_rom_text

        return extract_rom_text(ROM_PATH)
    except Exception:
        return {}


def reload_rom_names() -> None:
    data = _extract_rom_dictionary()

    def table(name: str) -> dict[int, str]:
        result: dict[int, str] = {}
        for key, entry in data.get(name, {}).items():
            try:
                item_id = int(key)
            except ValueError:
                continue
            value = str(entry.get("name") or entry.get("decoded") or "")
            result[item_id] = value or f"{name} {item_id}"
        return result

    SPECIES_NAMES.update(table("species"))
    ITEM_NAMES.update(table("items"))
    MOVE_NAMES.clear()
    MOVE_NAMES.update(table("moves"))
    ABILITY_NAMES.clear()
    ABILITY_NAMES.update(table("abilities"))


reload_rom_names()


def _load_base_stats() -> dict[int, bytes]:
    if ROM_PATH is None or not ROM_PATH.exists():
        return {}
    try:
        rom = ROM_PATH.read_bytes()
    except OSError:
        return {}
    stats: dict[int, bytes] = {}
    for species_id in range(0, 1025):
        start = BASE_STATS_OFFSET + species_id * BASE_STATS_SIZE
        end = start + BASE_STATS_SIZE
        if end > len(rom):
            break
        stats[species_id] = rom[start:end]
    return stats


BASE_STATS = _load_base_stats()


def set_rom_path(path: Path | str | None) -> None:
    global ROM_PATH, BASE_STATS
    ROM_PATH = Path(path).expanduser() if path else None
    _read_rom.cache_clear()
    constraints_for_species.cache_clear()
    _previous_species_by_target.cache_clear()
    BASE_STATS = _load_base_stats()
    reload_rom_names()


@dataclass(frozen=True)
class SectionRef:
    block_base: int
    section_offset: int
    section_id: int
    save_index: int

    @property
    def absolute_offset(self) -> int:
        return self.block_base + self.section_offset


@dataclass
class BagEntry:
    pocket: str
    slot: int
    item_id: int
    quantity: int

    @property
    def item_name(self) -> str:
        return format_item(self.item_id)


@dataclass
class PokemonView:
    slot: int
    raw: bytes
    personality: int
    ot_id: int
    species: int
    held_item: int
    experience: int
    friendship: int
    moves: list[int]
    pps: list[int]
    evs: list[int]
    ivs: list[int]
    ability_bit: int
    ability_id: int
    is_egg: bool
    nature_id: int
    gender: str
    is_shiny: bool
    caught_ball: int
    checksum_stored: int
    checksum_calculated: int
    level: int
    current_hp: int
    max_hp: int
    attack: int
    defense: int
    speed: int
    sp_attack: int
    sp_defense: int
    box: int = 0
    box_slot: int = 0

    @property
    def species_name(self) -> str:
        return SPECIES_NAMES.get(self.species, f"种族 {self.species}")

    @property
    def held_item_name(self) -> str:
        if self.held_item == 0:
            return "空"
        return format_item(self.held_item)

    @property
    def nature_name(self) -> str:
        return NATURE_NAMES[self.nature_id] if 0 <= self.nature_id < len(NATURE_NAMES) else f"性格 {self.nature_id}"

    @property
    def ability_name(self) -> str:
        if self.ability_id == 0:
            return "无"
        return ABILITY_NAMES.get(self.ability_id, f"特性 {self.ability_id}")

    @property
    def caught_ball_name(self) -> str:
        return BALL_NAMES.get(self.caught_ball, f"球 {self.caught_ball}")

    @property
    def is_empty(self) -> bool:
        return self.personality == 0 and self.ot_id == 0 and all(b == 0 for b in self.raw)


@dataclass(frozen=True)
class SpeciesConstraints:
    species_id: int
    ability_options: list[tuple[int, int]]
    gender_options: list[str]
    level_up_moves: dict[int, list[int]]
    pre_evolution_level_up_moves: dict[int, dict[int, list[int]]]
    egg_moves: set[int]
    pre_evolution_egg_moves: dict[int, set[int]]
    tmhm_moves: dict[int, int]
    tutor_moves: dict[int, int]


@dataclass(frozen=True)
class MoveLegality:
    move_id: int
    sources: list[str]
    future_levels: list[int]

    @property
    def is_known_legal(self) -> bool:
        return bool(self.sources)


class SaveFormatError(ValueError):
    pass


class EmeraldSave:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = bytearray(self.path.read_bytes())
        if len(self.data) < 0x1C000:
            raise SaveFormatError("文件太小，不像 128KB 三代 GBA .sav")
        self.sections = self._read_sections()
        self.active_base = self._select_active_block()

    def _read_sections(self) -> dict[int, dict[int, SectionRef]]:
        blocks: dict[int, dict[int, SectionRef]] = {}
        for base in (0, SAVE_BLOCK_SIZE):
            refs: dict[int, SectionRef] = {}
            for i in range(14):
                off = i * SECTION_SIZE
                abs_off = base + off
                sec = self.data[abs_off : abs_off + SECTION_SIZE]
                section_id = _u16(sec, 0x0FF4)
                checksum = _u16(sec, 0x0FF6)
                signature = _u32(sec, 0x0FF8)
                save_index = _u32(sec, 0x0FFC)
                if section_id in SECTION_CHECKSUM_SIZES and signature == SIGNATURE:
                    if checksum == self.section_checksum(sec, section_id):
                        refs[section_id] = SectionRef(base, off, section_id, save_index)
            blocks[base] = refs
        return blocks

    def _select_active_block(self) -> int:
        valid = [base for base, refs in self.sections.items() if len(refs) == 14]
        if not valid:
            raise SaveFormatError("没有找到完整且校验正确的存档槽")
        if len(valid) == 1:
            return valid[0]
        a_last = self.sections[0][self._last_physical_section_id(0)].save_index
        b_last = self.sections[SAVE_BLOCK_SIZE][self._last_physical_section_id(SAVE_BLOCK_SIZE)].save_index
        return 0 if a_last > b_last else SAVE_BLOCK_SIZE

    def _last_physical_section_id(self, base: int) -> int:
        sec = self.data[base + 13 * SECTION_SIZE : base + 14 * SECTION_SIZE]
        return _u16(sec, 0x0FF4)

    @staticmethod
    def section_checksum(section: bytes | bytearray, section_id: int) -> int:
        size = SECTION_CHECKSUM_SIZES[section_id]
        total = 0
        for offset in range(0, size, 4):
            total = (total + int.from_bytes(section[offset : offset + 4], "little")) & 0xFFFFFFFF
        return ((total >> 16) + (total & 0xFFFF)) & 0xFFFF

    def section_ref(self, section_id: int) -> SectionRef:
        return self.sections[self.active_base][section_id]

    def section_data_offset(self, section_id: int, rel_offset: int) -> int:
        return self.section_ref(section_id).absolute_offset + rel_offset

    def security_key(self) -> int:
        primary = _u32(self.data, self.section_data_offset(0, SECURITY_KEY_OFFSET))
        copy = _u32(self.data, self.section_data_offset(0, SECURITY_KEY_COPY_OFFSET))
        return primary or copy

    def trainer_summary(self) -> dict:
        name_raw = bytes(self.data[self.section_data_offset(0, TRAINER_NAME_OFFSET) : self.section_data_offset(0, TRAINER_NAME_OFFSET) + TRAINER_NAME_SIZE])
        printable_name = "".join(chr(byte) if 0x20 <= byte <= 0x7E else "." for byte in name_raw if byte not in (0x00, 0xFF))
        gender_value = self.data[self.section_data_offset(0, TRAINER_GENDER_OFFSET)]
        return {
            "name_raw": name_raw.hex(" ").upper(),
            "name_ascii": printable_name,
            "gender_value": gender_value,
            "gender": {0: "男", 1: "女"}.get(gender_value, f"未知 {gender_value}"),
            "trainer_id": _u16(self.data, self.section_data_offset(0, TRAINER_ID_OFFSET)),
            "secret_id": _u16(self.data, self.section_data_offset(0, SECRET_ID_OFFSET)),
            "play_time": {
                "hours": _u16(self.data, self.section_data_offset(0, PLAY_TIME_HOURS_OFFSET)),
                "minutes": self.data[self.section_data_offset(0, PLAY_TIME_MINUTES_OFFSET)],
                "seconds": self.data[self.section_data_offset(0, PLAY_TIME_SECONDS_OFFSET)],
                "frames": self.data[self.section_data_offset(0, PLAY_TIME_FRAMES_OFFSET)],
            },
        }

    def inventory_summary(self) -> dict:
        key = self.security_key()
        return {
            "money": _u32(self.data, self.section_data_offset(1, MONEY_OFFSET)) ^ key,
            "coins": _u16(self.data, self.section_data_offset(1, COINS_OFFSET)) ^ (key & 0xFFFF),
        }

    def section_summary(self) -> list[dict]:
        rows = []
        for base, refs in sorted(self.sections.items()):
            slot = "A" if base == 0 else "B"
            active = base == self.active_base
            for section_id in range(14):
                ref = refs.get(section_id)
                if not ref:
                    rows.append({"slot": slot, "active": active, "section_id": section_id, "ok": False})
                    continue
                off = ref.absolute_offset
                sec = self.data[off : off + SECTION_SIZE]
                stored = _u16(sec, 0x0FF6)
                calc = self.section_checksum(sec, section_id)
                rows.append({
                    "slot": slot,
                    "active": active,
                    "section_id": section_id,
                    "physical_index": ref.section_offset // SECTION_SIZE,
                    "save_index": ref.save_index,
                    "checksum": f"0x{stored:04X}",
                    "calculated": f"0x{calc:04X}",
                    "ok": stored == calc,
                })
        return rows

    def party_count(self) -> int:
        return min(_u32(self.data, self.section_data_offset(1, PARTY_COUNT_OFFSET)), 6)

    def party(self) -> list[PokemonView]:
        count = self.party_count()
        result = []
        base = self.section_data_offset(1, PARTY_OFFSET)
        for slot in range(count):
            raw = bytes(self.data[base + slot * PARTY_SIZE : base + (slot + 1) * PARTY_SIZE])
            result.append(parse_pokemon(raw, slot + 1))
        return result

    def box_storage_bytes(self) -> bytes:
        chunks = bytearray()
        for section_id in BOX_SECTION_IDS:
            ref = self.section_ref(section_id)
            payload_size = SECTION_CHECKSUM_SIZES[section_id]
            chunks.extend(self.data[ref.absolute_offset : ref.absolute_offset + payload_size])
        return bytes(chunks[: BOX_DATA_OFFSET + BOX_DATA_SIZE])

    def boxes(self, include_empty: bool = False) -> list[PokemonView]:
        storage = self.box_storage_bytes()[BOX_DATA_OFFSET : BOX_DATA_OFFSET + BOX_DATA_SIZE]
        result: list[PokemonView] = []
        for index in range(BOX_COUNT * BOX_SLOTS):
            start = index * BOX_POKEMON_SIZE
            raw = storage[start : start + BOX_POKEMON_SIZE]
            if len(raw) < BOX_POKEMON_SIZE:
                break
            pokemon = parse_pokemon(raw, index + 1)
            pokemon.box = index // BOX_SLOTS + 1
            pokemon.box_slot = index % BOX_SLOTS + 1
            if include_empty or not pokemon.is_empty:
                result.append(pokemon)
        return result

    def read_bag(self) -> list[BagEntry]:
        key16 = self.security_key() & 0xFFFF
        entries: list[BagEntry] = []
        for pocket, (offset, count, encrypted) in BAG_POCKETS.items():
            base = self.section_data_offset(1, offset)
            for slot in range(count):
                item_id = _u16(self.data, base + slot * 4)
                raw_qty = _u16(self.data, base + slot * 4 + 2)
                qty = 0 if item_id == 0 else raw_qty ^ key16 if encrypted else raw_qty
                entries.append(BagEntry(pocket, slot + 1, item_id, qty))
        return entries

    def write_bag_entry(self, entry: BagEntry) -> None:
        offset, count, encrypted = BAG_POCKETS[entry.pocket]
        if not (1 <= entry.slot <= count):
            raise ValueError("背包格位超出范围")
        item_id = _clamp_int(entry.item_id, 0, 65535)
        qty = _clamp_int(entry.quantity, 0, 999)
        base = self.section_data_offset(1, offset) + (entry.slot - 1) * 4
        _w16(self.data, base, item_id)
        stored_qty = qty ^ (self.security_key() & 0xFFFF) if encrypted and item_id else qty
        _w16(self.data, base + 2, stored_qty)
        self.fix_section_checksum(1)

    def update_party_pokemon(self, slot: int, updates: dict[str, int | list[int]]) -> PokemonView:
        if not (1 <= slot <= self.party_count()):
            raise ValueError("队伍槽位超出范围")
        base = self.section_data_offset(1, PARTY_OFFSET) + (slot - 1) * PARTY_SIZE
        raw = bytes(self.data[base : base + PARTY_SIZE])
        edited = edit_pokemon(raw, updates)
        self.data[base : base + PARTY_SIZE] = edited
        self.fix_section_checksum(1)
        return parse_pokemon(bytes(edited), slot)

    def update_box_pokemon(self, box: int, box_slot: int, updates: dict[str, int | list[int]]) -> PokemonView:
        if not (1 <= box <= BOX_COUNT):
            raise ValueError("盒子编号超出范围")
        if not (1 <= box_slot <= BOX_SLOTS):
            raise ValueError("盒子格位超出范围")
        index = (box - 1) * BOX_SLOTS + (box_slot - 1)
        storage_offset = BOX_DATA_OFFSET + index * BOX_POKEMON_SIZE
        raw = self._read_box_storage_range(storage_offset, BOX_POKEMON_SIZE)
        edited = edit_pokemon(raw, updates)
        touched_sections = self._write_box_storage_range(storage_offset, edited)
        for section_id in touched_sections:
            self.fix_section_checksum(section_id)
        pokemon = parse_pokemon(bytes(edited), index + 1)
        pokemon.box = box
        pokemon.box_slot = box_slot
        return pokemon

    def _read_box_storage_range(self, storage_offset: int, size: int) -> bytes:
        if storage_offset < 0 or storage_offset + size > BOX_DATA_OFFSET + BOX_DATA_SIZE:
            raise ValueError("盒子数据偏移超出范围")
        remaining_offset = storage_offset
        remaining_size = size
        out = bytearray()
        for section_id in BOX_SECTION_IDS:
            payload_size = SECTION_CHECKSUM_SIZES[section_id]
            if remaining_offset >= payload_size:
                remaining_offset -= payload_size
                continue
            take = min(remaining_size, payload_size - remaining_offset)
            start = self.section_ref(section_id).absolute_offset + remaining_offset
            out.extend(self.data[start : start + take])
            remaining_size -= take
            remaining_offset = 0
            if remaining_size == 0:
                return bytes(out)
        raise ValueError("盒子数据读取不完整")

    def _write_box_storage_range(self, storage_offset: int, payload: bytes | bytearray) -> set[int]:
        if storage_offset < 0 or storage_offset + len(payload) > BOX_DATA_OFFSET + BOX_DATA_SIZE:
            raise ValueError("盒子数据偏移超出范围")
        remaining_offset = storage_offset
        payload_offset = 0
        touched_sections: set[int] = set()
        for section_id in BOX_SECTION_IDS:
            payload_size = SECTION_CHECKSUM_SIZES[section_id]
            if remaining_offset >= payload_size:
                remaining_offset -= payload_size
                continue
            take = min(len(payload) - payload_offset, payload_size - remaining_offset)
            start = self.section_ref(section_id).absolute_offset + remaining_offset
            self.data[start : start + take] = payload[payload_offset : payload_offset + take]
            touched_sections.add(section_id)
            payload_offset += take
            remaining_offset = 0
            if payload_offset == len(payload):
                return touched_sections
        raise ValueError("盒子数据写入不完整")

    def fix_section_checksum(self, section_id: int) -> None:
        ref = self.section_ref(section_id)
        off = ref.absolute_offset
        checksum = self.section_checksum(self.data[off : off + SECTION_SIZE], section_id)
        _w16(self.data, off + 0x0FF6, checksum)

    def validate(self) -> list[str]:
        messages: list[str] = []
        for base, refs in self.sections.items():
            label = "A" if base == 0 else "B"
            if len(refs) != 14:
                messages.append(f"{label} 槽 section 不完整：{len(refs)}/14")
                continue
            indexes = {ref.save_index for ref in refs.values()}
            if len(indexes) != 1:
                messages.append(f"{label} 槽 save index 不一致：{sorted(indexes)}")
            for sid, ref in sorted(refs.items()):
                sec = self.data[ref.absolute_offset : ref.absolute_offset + SECTION_SIZE]
                stored = _u16(sec, 0x0FF6)
                calc = self.section_checksum(sec, sid)
                if stored != calc:
                    messages.append(f"{label} 槽 section {sid} 校验错误：{stored:04X} != {calc:04X}")
        for pokemon in self.party():
            messages.extend(validate_pokemon(pokemon, f"队伍 {pokemon.slot}"))
        return messages

    def save(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = self.path.with_name(f"{self.path.stem}.bak-{stamp}{self.path.suffix}")
        shutil.copy2(self.path, backup)
        self.path.write_bytes(self.data)
        return backup


def parse_pokemon(raw: bytes, slot: int = 0) -> PokemonView:
    if len(raw) < 80:
        raise ValueError("宝可梦数据长度不足")
    personality = _u32(raw, 0)
    ot_id = _u32(raw, 4)
    checksum_stored = _u16(raw, 0x1C)
    decrypted = decrypt_substructures(raw)
    checksum_calculated = pokemon_checksum(decrypted)
    parts = split_substructures(personality, decrypted)
    growth = parts["G"]
    attacks = parts["A"]
    evs = parts["E"]
    misc = parts["M"]
    iv_word = _u32(misc, 4)
    origin_word = _u16(misc, 2)
    iv_values = [(iv_word >> shift) & 0x1F for shift in (0, 5, 10, 15, 20, 25)]
    species = _u16(growth, 0)
    experience = _u32(growth, 4)
    ability_bit = (iv_word >> 31) & 1
    if len(raw) >= 100:
        level = raw[0x54]
        current_hp = _u16(raw, 0x56)
        max_hp = _u16(raw, 0x58)
        attack = _u16(raw, 0x5A)
        defense = _u16(raw, 0x5C)
        speed = _u16(raw, 0x5E)
        sp_attack = _u16(raw, 0x60)
        sp_defense = _u16(raw, 0x62)
    else:
        level = level_for_experience(species, experience)
        current_hp = max_hp = attack = defense = speed = sp_attack = sp_defense = 0
    return PokemonView(
        slot=slot,
        raw=raw,
        personality=personality,
        ot_id=ot_id,
        species=species,
        held_item=_u16(growth, 2),
        experience=experience,
        friendship=growth[9],
        moves=[_u16(attacks, i * 2) for i in range(4)],
        pps=[attacks[8 + i] for i in range(4)],
        evs=list(evs[:6]),
        ivs=iv_values,
        ability_bit=ability_bit,
        ability_id=ability_id_for_species(species, ability_bit),
        is_egg=bool((iv_word >> 30) & 1),
        nature_id=personality % 25,
        gender=gender_for_species(species, personality),
        is_shiny=is_shiny(personality, ot_id),
        caught_ball=(origin_word >> 11) & 0xF,
        checksum_stored=checksum_stored,
        checksum_calculated=checksum_calculated,
        level=level,
        current_hp=current_hp,
        max_hp=max_hp,
        attack=attack,
        defense=defense,
        speed=speed,
        sp_attack=sp_attack,
        sp_defense=sp_defense,
    )


def edit_pokemon(raw: bytes, updates: dict[str, int | list[int]]) -> bytes:
    buf = bytearray(raw)
    personality = _u32(buf, 0)
    ot_id = _u32(buf, 4)
    decrypted = bytearray(decrypt_substructures(buf))
    parts = split_substructures(personality, decrypted)
    manual_personality = "personality" in updates
    if manual_personality:
        personality = _clamp_int(int(updates["personality"]), 0, 0xFFFFFFFF)
        _w32(buf, 0, personality)
    if "species" in updates:
        _w16(parts["G"], 0, _clamp_int(int(updates["species"]), 0, 65535))
    if "held_item" in updates:
        _w16(parts["G"], 2, _clamp_int(int(updates["held_item"]), 0, 65535))
    if "experience" in updates:
        _w32(parts["G"], 4, _clamp_int(int(updates["experience"]), 0, 0xFFFFFFFF))
    if "friendship" in updates:
        parts["G"][9] = _clamp_int(int(updates["friendship"]), 0, 255)
    if "caught_ball" in updates:
        old = _u16(parts["M"], 2)
        ball = _clamp_int(int(updates["caught_ball"]), 0, 15)
        _w16(parts["M"], 2, (old & ~(0xF << 11)) | (ball << 11))
    if "moves" in updates:
        moves = list(updates["moves"])  # type: ignore[arg-type]
        for i in range(4):
            _w16(parts["A"], i * 2, _clamp_int(int(moves[i]), 0, 65535))
    if "pps" in updates:
        pps = list(updates["pps"])  # type: ignore[arg-type]
        for i in range(4):
            parts["A"][8 + i] = _clamp_int(int(pps[i]), 0, 99)
    if "evs" in updates:
        evs = list(updates["evs"])  # type: ignore[arg-type]
        for i in range(6):
            parts["E"][i] = _clamp_int(int(evs[i]), 0, 255)
    if "ivs" in updates or "ability_bit" in updates or "is_egg" in updates:
        old = _u32(parts["M"], 4)
        ivs = list(updates.get("ivs", [(old >> shift) & 0x1F for shift in (0, 5, 10, 15, 20, 25)]))  # type: ignore[arg-type]
        ability = _clamp_int(int(updates.get("ability_bit", (old >> 31) & 1)), 0, 1)
        egg = 1 if bool(updates.get("is_egg", bool((old >> 30) & 1))) else 0
        word = 0
        for i, iv in enumerate(ivs[:6]):
            word |= _clamp_int(int(iv), 0, 31) << (i * 5)
        word |= egg << 30
        word |= ability << 31
        _w32(parts["M"], 4, word)
    if not manual_personality:
        target_personality = adjust_personality(
            personality,
            ot_id,
            _u16(parts["G"], 0),
            nature_id=int(updates["nature_id"]) if "nature_id" in updates else None,
            gender=str(updates["gender"]) if "gender" in updates else None,
            shiny=bool(updates["is_shiny"]) if "is_shiny" in updates else None,
        )
        if target_personality != personality:
            _w32(buf, 0, target_personality)
            personality = target_personality
    rebuilt = join_substructures(personality, parts)
    _w16(buf, 0x1C, pokemon_checksum(rebuilt))
    encrypted = encrypt_substructures(buf, rebuilt)
    buf[0x20:0x50] = encrypted
    if "level" in updates and len(buf) >= 100:
        buf[0x54] = _clamp_int(int(updates["level"]), 1, 100)
    if "current_hp" in updates and len(buf) >= 100:
        _w16(buf, 0x56, _clamp_int(int(updates["current_hp"]), 0, 9999))
    return bytes(buf)


def decrypt_substructures(raw: bytes | bytearray) -> bytes:
    key = _u32(raw, 0) ^ _u32(raw, 4)
    out = bytearray(48)
    for i in range(0, 48, 4):
        value = _u32(raw, 0x20 + i) ^ key
        _w32(out, i, value)
    return bytes(out)


def encrypt_substructures(raw: bytes | bytearray, decrypted: bytes | bytearray) -> bytes:
    key = _u32(raw, 0) ^ _u32(raw, 4)
    out = bytearray(48)
    for i in range(0, 48, 4):
        _w32(out, i, _u32(decrypted, i) ^ key)
    return bytes(out)


def split_substructures(personality: int, decrypted: bytes | bytearray) -> dict[str, bytearray]:
    order = SUBSTRUCT_ORDERS[personality % 24]
    return {name: bytearray(decrypted[i * 12 : (i + 1) * 12]) for i, name in enumerate(order)}


def join_substructures(personality: int, parts: dict[str, bytearray]) -> bytes:
    order = SUBSTRUCT_ORDERS[personality % 24]
    out = bytearray()
    for name in order:
        part = parts[name]
        if len(part) != 12:
            raise ValueError("宝可梦子结构长度错误")
        out.extend(part)
    return bytes(out)


def pokemon_checksum(decrypted: bytes | bytearray) -> int:
    total = 0
    for i in range(0, 48, 2):
        total = (total + _u16(decrypted, i)) & 0xFFFF
    return total


def ability_id_for_species(species_id: int, ability_bit: int) -> int:
    stats = BASE_STATS.get(species_id)
    if not stats or len(stats) < 24:
        return 0
    first = stats[22]
    second = stats[23]
    return second if ability_bit and second else first


def gender_ratio_for_species(species_id: int) -> int | None:
    stats = BASE_STATS.get(species_id)
    if not stats or len(stats) < 17:
        return None
    return stats[16]


def gender_for_species(species_id: int, personality: int) -> str:
    ratio = gender_ratio_for_species(species_id)
    if ratio is None or ratio == 255:
        return "无性别"
    if ratio == 254:
        return "雌"
    if ratio == 0:
        return "雄"
    return "雌" if (personality & 0xFF) < ratio else "雄"


def ability_options_for_species(species_id: int) -> list[tuple[int, int]]:
    stats = BASE_STATS.get(species_id)
    if not stats or len(stats) < 24:
        return []
    options = [(0, stats[22])]
    if stats[23]:
        options.append((1, stats[23]))
    return [(bit, ability_id) for bit, ability_id in options if ability_id]


def gender_options_for_species(species_id: int) -> list[str]:
    ratio = gender_ratio_for_species(species_id)
    if ratio is None or ratio == 255:
        return ["无性别"]
    if ratio == 254:
        return ["雌"]
    if ratio == 0:
        return ["雄"]
    return ["雄", "雌"]


def growth_rate_for_species(species_id: int) -> int | None:
    stats = BASE_STATS.get(species_id)
    if not stats or len(stats) <= BASE_STATS_GROWTH_RATE_OFFSET:
        return None
    return stats[BASE_STATS_GROWTH_RATE_OFFSET]


def experience_for_level(growth_rate: int, level: int) -> int:
    level = _clamp_int(level, 1, 100)
    cube = level * level * level
    if growth_rate == 0:
        return cube
    if growth_rate == 1:
        if level <= 50:
            return cube * (100 - level) // 50
        if level <= 68:
            return cube * (150 - level) // 100
        if level <= 98:
            return cube * ((1911 - 10 * level) // 3) // 500
        return cube * (160 - level) // 100
    if growth_rate == 2:
        if level <= 15:
            return cube * (((level + 1) // 3) + 24) // 50
        if level <= 36:
            return cube * (level + 14) // 50
        return cube * ((level // 2) + 32) // 50
    if growth_rate == 3:
        return max(0, (6 * cube) // 5 - 15 * level * level + 100 * level - 140)
    if growth_rate == 4:
        return 4 * cube // 5
    if growth_rate == 5:
        return 5 * cube // 4
    return cube


def level_for_experience(species_id: int, experience: int) -> int:
    growth_rate = growth_rate_for_species(species_id)
    if growth_rate is None:
        return 0
    experience = max(0, int(experience))
    level = 1
    for candidate in range(2, 101):
        if experience_for_level(growth_rate, candidate) > experience:
            break
        level = candidate
    return level


@lru_cache(maxsize=ROM_SPECIES_COUNT + 1)
def constraints_for_species(species_id: int) -> SpeciesConstraints | None:
    if not (0 <= species_id <= ROM_SPECIES_COUNT):
        return None
    rom = _read_rom()
    if not rom:
        return None
    return SpeciesConstraints(
        species_id=species_id,
        ability_options=ability_options_for_species(species_id),
        gender_options=gender_options_for_species(species_id),
        level_up_moves=_level_up_moves_for_species(rom, species_id),
        pre_evolution_level_up_moves=_pre_evolution_level_up_moves(rom, species_id),
        egg_moves=_egg_moves_by_species(rom).get(species_id, set()),
        pre_evolution_egg_moves=_pre_evolution_egg_moves(rom, species_id),
        tmhm_moves=_tmhm_moves_for_species(rom, species_id),
        tutor_moves=_tutor_moves_for_species(rom, species_id),
    )


def rom_constraints_loaded() -> bool:
    return bool(_read_rom())


def move_legality_for_species(species_id: int, level: int, move_id: int) -> MoveLegality:
    if move_id == 0:
        return MoveLegality(move_id=move_id, sources=["空"], future_levels=[])
    constraints = constraints_for_species(species_id)
    if constraints is None:
        return MoveLegality(move_id=move_id, sources=[], future_levels=[])
    sources: list[str] = []
    future_levels: list[int] = []
    learned_levels = constraints.level_up_moves.get(move_id, [])
    current_levels = [learn_level for learn_level in learned_levels if learn_level <= level]
    future_levels = [learn_level for learn_level in learned_levels if learn_level > level]
    if current_levels:
        levels = "/".join(str(learn_level) for learn_level in sorted(current_levels))
        sources.append(f"升级Lv{levels}")
    for pre_species_id, levels in sorted(constraints.pre_evolution_level_up_moves.get(move_id, {}).items()):
        pre_current = [learn_level for learn_level in levels if learn_level <= level]
        pre_future = [learn_level for learn_level in levels if learn_level > level]
        if pre_current:
            readable_levels = "/".join(str(learn_level) for learn_level in sorted(pre_current))
            sources.append(f"前置{format_species(pre_species_id)}Lv{readable_levels}")
        future_levels.extend(pre_future)
    if move_id in constraints.tmhm_moves:
        sources.append(f"TM/HM{constraints.tmhm_moves[move_id]:02d}")
    if move_id in constraints.tutor_moves:
        sources.append(f"定点教学{constraints.tutor_moves[move_id]:02d}")
    if move_id in constraints.egg_moves:
        sources.append("遗传")
    for pre_species_id in sorted(constraints.pre_evolution_egg_moves.get(move_id, set())):
        sources.append(f"前置{format_species(pre_species_id)}遗传")
    return MoveLegality(move_id=move_id, sources=sources, future_levels=future_levels)


def default_pp_for_move(move_id: int) -> int:
    if not (1 <= move_id <= ROM_MOVE_COUNT):
        return 0
    rom = _read_rom()
    offset = MOVE_DATA_OFFSET + move_id * MOVE_DATA_SIZE + MOVE_PP_OFFSET
    if not rom or offset >= len(rom):
        return 0
    return rom[offset]


@lru_cache(maxsize=1)
def _read_rom() -> bytes:
    if ROM_PATH is None or not ROM_PATH.exists():
        return b""
    try:
        return ROM_PATH.read_bytes()
    except OSError:
        return b""


def _level_up_moves_for_species(rom: bytes, species_id: int) -> dict[int, list[int]]:
    if not (0 <= species_id <= ROM_SPECIES_COUNT):
        return {}
    learnset_index = species_id + LEVEL_UP_LEARNSET_SPECIES_OFFSET
    if not (0 <= learnset_index <= ROM_SPECIES_COUNT):
        return {}
    pointer_offset = LEVEL_UP_LEARNSET_POINTERS_OFFSET + learnset_index * 4
    if pointer_offset + 4 > len(rom):
        return {}
    pointer = struct.unpack_from("<I", rom, pointer_offset)[0]
    learnset_offset = pointer - GBA_ROM_POINTER_BASE
    if not (0 <= learnset_offset < len(rom)):
        return {}
    moves: dict[int, list[int]] = {}
    offset = learnset_offset
    for _ in range(100):
        if offset + 2 > len(rom):
            break
        value = struct.unpack_from("<H", rom, offset)[0]
        offset += 2
        if value == 0xFFFF:
            break
        move_id = value & 0x01FF
        level = value >> 9
        if not (1 <= move_id <= ROM_MOVE_COUNT and 1 <= level <= 100):
            break
        moves.setdefault(move_id, []).append(level)
    return moves


@lru_cache(maxsize=1)
def _previous_species_by_target() -> dict[int, set[int]]:
    rom = _read_rom()
    result: dict[int, set[int]] = {}
    if not rom:
        return result
    for species_id in range(0, ROM_SPECIES_COUNT + 1):
        record_offset = EVOLUTIONS_OFFSET + species_id * EVOLUTION_RECORD_SIZE
        if record_offset + EVOLUTION_RECORD_SIZE > len(rom):
            break
        for entry_index in range(EVOLUTIONS_PER_SPECIES):
            entry_offset = record_offset + entry_index * EVOLUTION_ENTRY_SIZE
            method, _param, target_species, _padding = struct.unpack_from("<HHHH", rom, entry_offset)
            if method and 1 <= target_species <= ROM_SPECIES_COUNT and target_species != species_id:
                result.setdefault(target_species, set()).add(species_id)
    return result


def pre_evolution_species_ids(species_id: int) -> list[int]:
    previous_by_target = _previous_species_by_target()
    result: set[int] = set()
    pending = list(previous_by_target.get(species_id, set()))
    while pending:
        previous = pending.pop()
        if previous in result:
            continue
        result.add(previous)
        pending.extend(previous_by_target.get(previous, set()))
    return sorted(result)


def _pre_evolution_level_up_moves(rom: bytes, species_id: int) -> dict[int, dict[int, list[int]]]:
    result: dict[int, dict[int, list[int]]] = {}
    for pre_species_id in pre_evolution_species_ids(species_id):
        for move_id, levels in _level_up_moves_for_species(rom, pre_species_id).items():
            result.setdefault(move_id, {})[pre_species_id] = sorted(set(levels))
    return result


def _pre_evolution_egg_moves(rom: bytes, species_id: int) -> dict[int, set[int]]:
    egg_moves_by_species = _egg_moves_by_species(rom)
    result: dict[int, set[int]] = {}
    for pre_species_id in pre_evolution_species_ids(species_id):
        for move_id in egg_moves_by_species.get(pre_species_id, set()):
            result.setdefault(move_id, set()).add(pre_species_id)
    return result


def _egg_moves_by_species(rom: bytes) -> dict[int, set[int]]:
    result: dict[int, set[int]] = {}
    offset = EGG_MOVES_OFFSET
    current_species: int | None = None
    while offset + 2 <= len(rom):
        value = struct.unpack_from("<H", rom, offset)[0]
        offset += 2
        if value == 0xFFFF:
            break
        if EGG_MOVE_SPECIES_MARKER_BASE < value <= EGG_MOVE_SPECIES_MARKER_BASE + ROM_SPECIES_COUNT:
            current_species = value - EGG_MOVE_SPECIES_MARKER_BASE
            result.setdefault(current_species, set())
            continue
        if current_species is not None and 1 <= value <= ROM_MOVE_COUNT:
            result[current_species].add(value)
            continue
        break
    return result


def _tmhm_move_ids(rom: bytes) -> list[int]:
    if TMHM_MOVES_OFFSET + TMHM_COUNT * 2 > len(rom):
        return []
    return list(struct.unpack_from("<" + "H" * TMHM_COUNT, rom, TMHM_MOVES_OFFSET))


def tmhm_move_for_item(item_id: int) -> int | None:
    if not (TMHM_FIRST_ITEM_ID <= item_id <= TMHM_LAST_ITEM_ID):
        return None
    rom = _read_rom()
    if not rom:
        return None
    index = item_id - TMHM_FIRST_ITEM_ID
    move_ids = _tmhm_move_ids(rom)
    if index >= len(move_ids):
        return None
    return move_ids[index]


def _tmhm_moves_for_species(rom: bytes, species_id: int) -> dict[int, int]:
    if not (0 <= species_id <= ROM_SPECIES_COUNT):
        return {}
    bitmap_offset = TMHM_COMPATIBILITY_OFFSET + species_id * TMHM_COMPATIBILITY_SIZE
    if bitmap_offset + TMHM_COMPATIBILITY_SIZE > len(rom):
        return {}
    bitmap = rom[bitmap_offset : bitmap_offset + TMHM_COMPATIBILITY_SIZE]
    tmhm_moves = _tmhm_move_ids(rom)
    result: dict[int, int] = {}
    for index, move_id in enumerate(tmhm_moves):
        if bitmap[index // 8] & (1 << (index % 8)):
            result[move_id] = index + 1
    return result


def _tutor_move_ids(rom: bytes) -> list[int]:
    result: list[int] = []
    offset = TUTOR_MOVES_OFFSET
    while offset + 2 <= len(rom):
        move_id = struct.unpack_from("<H", rom, offset)[0]
        offset += 2
        if move_id == 0:
            break
        if not (1 <= move_id <= ROM_MOVE_COUNT):
            return []
        result.append(move_id)
        if len(result) >= TUTOR_COMPATIBILITY_SIZE * 8:
            break
    return result


def _tutor_moves_for_species(rom: bytes, species_id: int) -> dict[int, int]:
    if not (0 <= species_id <= ROM_SPECIES_COUNT):
        return {}
    bitmap_offset = TUTOR_COMPATIBILITY_OFFSET + species_id * TUTOR_COMPATIBILITY_SIZE
    if bitmap_offset + TUTOR_COMPATIBILITY_SIZE > len(rom):
        return {}
    bitmap = rom[bitmap_offset : bitmap_offset + TUTOR_COMPATIBILITY_SIZE]
    tutor_moves = _tutor_move_ids(rom)
    result: dict[int, int] = {}
    for index, move_id in enumerate(tutor_moves):
        if bitmap[index // 8] & (1 << (index % 8)):
            result[move_id] = index + 1
    return result


def is_shiny(personality: int, ot_id: int) -> bool:
    value = ((ot_id & 0xFFFF) ^ (ot_id >> 16) ^ (personality & 0xFFFF) ^ (personality >> 16)) & 0xFFFF
    return value < 8


def adjust_personality(
    personality: int,
    ot_id: int,
    species_id: int,
    nature_id: int | None = None,
    gender: str | None = None,
    shiny: bool | None = None,
) -> int:
    target_nature = personality % 25 if nature_id is None else _clamp_int(nature_id, 0, 24)
    target_shiny = is_shiny(personality, ot_id) if shiny is None else shiny
    target_gender = gender_for_species(species_id, personality) if not gender else gender
    if (
        personality % 25 == target_nature
        and is_shiny(personality, ot_id) == target_shiny
        and gender_for_species(species_id, personality) == target_gender
    ):
        return personality
    if nature_id is None and shiny is None and (not gender or target_gender == gender_for_species(species_id, personality)):
        return personality
    start_low = personality & 0xFFFF
    shiny_values = range(8) if target_shiny else range(8, 16)
    for step in range(0x10000):
        low = (start_low + step) & 0xFFFF
        for shiny_value in shiny_values:
            high = ((ot_id & 0xFFFF) ^ (ot_id >> 16) ^ low ^ shiny_value) & 0xFFFF
            candidate = ((high << 16) | low) & 0xFFFFFFFF
            if candidate % 25 != target_nature:
                continue
            if is_shiny(candidate, ot_id) != target_shiny:
                continue
            actual_gender = gender_for_species(species_id, candidate)
            if target_gender in ("雄", "雌") and actual_gender != target_gender:
                continue
            return candidate
    raise ValueError("无法找到满足性格/性别/闪光组合的 PID")


def validate_pokemon(pokemon: PokemonView, label: str = "宝可梦", check_level: bool = True, move_level: int | None = None) -> list[str]:
    if pokemon.is_empty:
        return []
    issues: list[str] = []
    if pokemon.checksum_stored != pokemon.checksum_calculated:
        issues.append(f"{label} 数据校验错误：{pokemon.checksum_stored:04X} != {pokemon.checksum_calculated:04X}")
    if not (1 <= pokemon.species <= 1024):
        issues.append(f"{label} 种族编号异常：{pokemon.species}")
    if check_level and not (1 <= pokemon.level <= 100):
        issues.append(f"{label} 等级异常：{pokemon.level}")
    if sum(pokemon.evs) > 510:
        issues.append(f"{label} 努力值总和超过 510：{sum(pokemon.evs)}")
    for stat, value in zip(("体力", "物攻", "物防", "速度", "特攻", "特防"), pokemon.evs):
        if value > 255:
            issues.append(f"{label} {stat} 努力值超过 255：{value}")
    for stat, value in zip(("体力", "物攻", "物防", "速度", "特攻", "特防"), pokemon.ivs):
        if value > 31:
            issues.append(f"{label} {stat} 个体值超过 31：{value}")
    if pokemon.current_hp > pokemon.max_hp and pokemon.max_hp:
        issues.append(f"{label} 当前 HP 大于最大 HP：{pokemon.current_hp}/{pokemon.max_hp}")
    if any(pp > 64 for pp in pokemon.pps):
        issues.append(f"{label} PP 看起来过高：{pokemon.pps}")
    nonzero_moves = [move_id for move_id in pokemon.moves if move_id]
    duplicate_moves = sorted({move_id for move_id in nonzero_moves if nonzero_moves.count(move_id) > 1})
    if duplicate_moves:
        issues.append(f"{label} 招式重复：{', '.join(format_move(move_id) for move_id in duplicate_moves)}")
    for slot, move_id in enumerate(pokemon.moves, start=1):
        pp = pokemon.pps[slot - 1] if slot - 1 < len(pokemon.pps) else 0
        if move_id == 0:
            if pp:
                issues.append(f"{label} 招式槽 {slot} 为空但 PP 为 {pp}")
            continue
        if not (1 <= move_id <= ROM_MOVE_COUNT):
            issues.append(f"{label} 招式槽 {slot} 编号异常：{move_id}")
    constraints = constraints_for_species(pokemon.species)
    if constraints is None:
        if rom_constraints_loaded():
            issues.append(f"{label} 无法读取种族 {pokemon.species} 的 ROM 约束数据")
    else:
        valid_ability_bits = {bit for bit, _ in constraints.ability_options}
        if pokemon.ability_bit not in valid_ability_bits:
            readable_options = "、".join(f"{bit}:{format_ability(ability_id)}" for bit, ability_id in constraints.ability_options) or "无"
            issues.append(f"{label} 特性位异常：{pokemon.ability_bit}，当前种族可用特性位为 {readable_options}")
        expected_ability = ability_id_for_species(pokemon.species, pokemon.ability_bit)
        if pokemon.ability_id != expected_ability:
            issues.append(
                f"{label} 特性反查不一致：存档显示 {pokemon.ability_id} {format_ability(pokemon.ability_id)}，"
                f"按 ROM 应为 {expected_ability} {format_ability(expected_ability)}"
            )
        if pokemon.gender not in constraints.gender_options:
            issues.append(f"{label} 性别异常：{pokemon.gender}，当前种族可用性别为 {'、'.join(constraints.gender_options)}")
        for slot, move_id in enumerate(pokemon.moves, start=1):
            if move_id == 0:
                continue
            if not (1 <= move_id <= ROM_MOVE_COUNT):
                continue
            legality = move_legality_for_species(pokemon.species, move_level if move_level is not None else pokemon.level, move_id)
            if not legality.is_known_legal:
                future = f"，Lv{'/'.join(str(level) for level in legality.future_levels)} 可学" if legality.future_levels else ""
                issues.append(f"{label} 招式槽 {slot} 可疑：{move_id} {format_move(move_id)} 不在当前种族升级/TM-HM/遗传集合中{future}")
    if not issues:
        issues.append(f"{label} 合法性通过")
    return issues


def format_item(item_id: int) -> str:
    name = ITEM_NAMES.get(item_id, f"道具 {item_id}")
    move_id = tmhm_move_for_item(item_id)
    if move_id:
        return f"{name}（{format_move(move_id)}）"
    return name


def format_species(species_id: int) -> str:
    return SPECIES_NAMES.get(species_id, f"种族 {species_id}")


def format_move(move_id: int) -> str:
    return MOVE_NAMES.get(move_id, f"招式 {move_id}")


def format_ability(ability_id: int) -> str:
    return ABILITY_NAMES.get(ability_id, f"特性 {ability_id}")


def _u16(buf: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<H", buf, offset)[0]


def _u32(buf: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", buf, offset)[0]


def _w16(buf: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<H", buf, offset, value & 0xFFFF)


def _w32(buf: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", buf, offset, value & 0xFFFFFFFF)


def _clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def compact_nonempty(entries: Iterable[BagEntry]) -> list[BagEntry]:
    return [entry for entry in entries if entry.item_id or entry.quantity]
