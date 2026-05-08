from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NamedOffset:
    id: str
    offset: int
    role: str
    recognizer: str = ""


@dataclass(frozen=True)
class NameTableProfile:
    id: str
    table: str
    label: str
    offset: int
    entry_size: int
    text_size: int
    count: int
    extension_offset: int | None = None
    extension_start: int | None = None


@dataclass(frozen=True)
class ItemTableProfile:
    offset: int
    entry_size: int
    name_size: int
    count: int
    id_offset: int
    price_offset: int
    hold_effect_offset: int
    hold_param_offset: int
    description_pointer_offset: int
    pocket_offset: int
    type_offset: int
    secondary_id_offset: int


@dataclass(frozen=True)
class CreatureDataProfile:
    base_stats_offset: int
    base_stats_size: int
    move_data_offset: int
    move_data_size: int
    move_pp_offset: int
    move_description_pointers_offset: int
    ability_description_pointers_offset: int
    ability_description_extension_pointers_offset: int
    level_up_learnset_pointers_offset: int
    level_up_learnset_species_offset: int
    evolutions_offset: int
    evolution_entry_size: int
    evolutions_per_species: int
    egg_moves_offset: int
    tmhm_compatibility_offset: int
    tmhm_compatibility_size: int
    tmhm_moves_offset: int
    tmhm_count: int
    tutor_moves_offset: int
    tutor_compatibility_offset: int
    tutor_compatibility_size: int
    tmhm_first_item_id: int

    @property
    def evolution_record_size(self) -> int:
        return self.evolution_entry_size * self.evolutions_per_species

    @property
    def tmhm_last_item_id(self) -> int:
        return self.tmhm_first_item_id + self.tmhm_count - 1


@dataclass(frozen=True)
class WildEncounterProfile:
    active_headers_offset: int
    legacy_headers_offset: int
    header_size: int
    max_headers: int


@dataclass(frozen=True)
class MapProfile:
    active_map_groups_offset: int
    original_map_groups_offset: int
    region_map_entries_offset: int
    region_map_entry_size: int
    header_size: int
    layout_size: int
    events_size: int
    connection_size: int
    max_groups: int
    max_maps_per_group: int


@dataclass(frozen=True)
class ScriptProfile:
    command_lengths: dict[int, int]
    special_start_battle: int
    special_in_game_trade: int
    var_special_battle_species: int
    var_special_battle_level: int
    var_special_battle_item: int
    var_in_game_trade_index: int
    in_game_trade_table_offset: int
    in_game_trade_entry_size: int
    in_game_trade_received_species_offset: int
    in_game_trade_requested_species_offset: int
    in_game_trade_max_entries: int


@dataclass(frozen=True)
class SpriteProfile:
    front_sprite_table_offset: int
    normal_palette_table_offset: int
    shiny_palette_table_offset: int
    table_entry_size: int
    table_count: int
    width: int
    height: int


@dataclass(frozen=True)
class RomProfile:
    id: str
    label: str
    generation: int
    family: str
    address_refs: tuple[NamedOffset, ...]
    name_tables: tuple[NameTableProfile, ...]
    items: ItemTableProfile
    creature_data: CreatureDataProfile
    wild_encounters: WildEncounterProfile
    maps: MapProfile
    scripts: ScriptProfile
    sprites: SpriteProfile


BW_SCRIPT_COMMAND_LENGTHS = {
    0x00: 1,
    0x02: 1,
    0x03: 1,
    0x04: 5,
    0x05: 5,
    0x06: 6,
    0x07: 6,
    0x08: 2,
    0x09: 2,
    0x0F: 6,
    0x16: 5,
    0x19: 5,
    0x1A: 5,
    0x21: 5,
    0x25: 3,
    0x26: 5,
    0x27: 1,
    0x28: 3,
    0x29: 3,
    0x2B: 3,
    0x2A: 3,
    0x30: 6,
    0x33: 4,
    0x35: 3,
    0x43: 6,
    0x45: 5,
    0x47: 5,
    0x4F: 7,
    0x51: 3,
    0x53: 3,
    0x55: 3,
    0x2F: 3,
    0x31: 3,
    0x32: 1,
    0x5A: 1,
    0x5B: 1,
    0x66: 1,
    0x64: 3,
    0x67: 5,
    0x68: 1,
    0x69: 1,
    0x6A: 1,
    0x6B: 1,
    0x6C: 1,
    0x79: 15,
    0x7A: 3,
    0x80: 4,
    0x97: 2,
    0xA4: 3,
    0xA5: 1,
    0xB6: 6,
    0xB7: 1,
    0xC5: 1,
    0xDC: 2,
}


CURRENT_ROM_PROFILE = RomProfile(
    id="pokemon_emerald_ex_bw",
    label="漆黑的魅影 5.0EX BW",
    generation=3,
    family="pokeemerald-hack",
    address_refs=(
        NamedOffset("species_name_table.primary", 0x3185C8, "fixed-width text table", "411 species slots, 11-byte names"),
        NamedOffset("move_name_table.primary", 0x31977C, "fixed-width text table", "Gen3 move-name table with extension"),
        NamedOffset("move_name_table.extension", 0x1903207, "fixed-width text table extension", "custom move names from id 355"),
        NamedOffset("ability_name_table.primary", 0x31B6DB, "fixed-width text table", "ability names with extension"),
        NamedOffset("ability_name_table.extension", 0x1C00000, "fixed-width text table extension", "custom ability names from id 78"),
        NamedOffset("wild_encounter_headers.active", 0xEA2D34, "wild encounter header table", "valid header run ending with FF FF sentinel"),
        NamedOffset("map_groups.active", 0xE8C020, "map group pointer table", "group pointers whose first entry is a plausible MapHeader"),
        NamedOffset("map_groups.original", 0x486578, "fallback map group pointer table", "vanilla-style group pointer table"),
        NamedOffset("in_game_trade_table", 0x338EDC, "in-game trade table", "60-byte records indexed by var 0x8008 before special 0x00A2"),
    ),
    name_tables=(
        NameTableProfile("species.names", "species", "宝可梦", 0x3185C8, 11, 11, 412),
        NameTableProfile("moves.names", "moves", "招式", 0x31977C, 13, 13, 472, 0x1903207, 355),
        NameTableProfile("abilities.names", "abilities", "特性", 0x31B6DB, 13, 13, 151, 0x1C00000, 78),
    ),
    items=ItemTableProfile(
        offset=0x5839A0,
        entry_size=44,
        name_size=14,
        count=377,
        id_offset=14,
        price_offset=16,
        hold_effect_offset=18,
        hold_param_offset=19,
        description_pointer_offset=20,
        pocket_offset=26,
        type_offset=27,
        secondary_id_offset=40,
    ),
    creature_data=CreatureDataProfile(
        base_stats_offset=0x3203CC,
        base_stats_size=28,
        move_data_offset=0x1900000,
        move_data_size=12,
        move_pp_offset=4,
        move_description_pointers_offset=0x1904A00,
        ability_description_pointers_offset=0x31BAD4,
        ability_description_extension_pointers_offset=0x1BFFE00,
        level_up_learnset_pointers_offset=0x329378,
        level_up_learnset_species_offset=1,
        evolutions_offset=0x32531C,
        evolution_entry_size=8,
        evolutions_per_species=5,
        egg_moves_offset=0x32ADD8,
        tmhm_compatibility_offset=0x31E898,
        tmhm_compatibility_size=8,
        tmhm_moves_offset=0x1CA0000,
        tmhm_count=58,
        tutor_moves_offset=0x61500C,
        tutor_compatibility_offset=0x615048,
        tutor_compatibility_size=4,
        tmhm_first_item_id=0x121,
    ),
    wild_encounters=WildEncounterProfile(
        active_headers_offset=0xEA2D34,
        legacy_headers_offset=0x552D48,
        header_size=20,
        max_headers=600,
    ),
    maps=MapProfile(
        active_map_groups_offset=0xE8C020,
        original_map_groups_offset=0x486578,
        region_map_entries_offset=0x5A1480,
        region_map_entry_size=8,
        header_size=0x1C,
        layout_size=0x18,
        events_size=0x14,
        connection_size=0x0C,
        max_groups=80,
        max_maps_per_group=300,
    ),
    scripts=ScriptProfile(
        command_lengths=BW_SCRIPT_COMMAND_LENGTHS,
        special_start_battle=0x01E2,
        special_in_game_trade=0x00A2,
        var_special_battle_species=0x8004,
        var_special_battle_level=0x8005,
        var_special_battle_item=0x8006,
        var_in_game_trade_index=0x8008,
        in_game_trade_table_offset=0x338EDC,
        in_game_trade_entry_size=60,
        in_game_trade_received_species_offset=0,
        in_game_trade_requested_species_offset=28,
        in_game_trade_max_entries=16,
    ),
    sprites=SpriteProfile(
        front_sprite_table_offset=0x30A18C,
        normal_palette_table_offset=0x303678,
        shiny_palette_table_offset=0x304438,
        table_entry_size=8,
        table_count=440,
        width=64,
        height=64,
    ),
)
