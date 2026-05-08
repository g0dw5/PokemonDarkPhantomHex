from __future__ import annotations

from dataclasses import dataclass


GBA_ROM_POINTER_BASE = 0x08000000
MAP_TILE_SIZE = 8
MAP_METATILE_SIZE = 16
TILESET_METATILE_COUNT = 512
DEFAULT_MAX_MAP_PIXELS = 2048 * 2048


def gba_pointer_to_offset(pointer: int, rom_size: int) -> int | None:
    offset = pointer - GBA_ROM_POINTER_BASE
    if 0 <= offset < rom_size:
        return offset
    return None


def valid_offset(offset: int | None, rom: bytes, size: int = 1) -> bool:
    return offset is not None and 0 <= offset <= len(rom) - size


def u16(rom: bytes, offset: int) -> int:
    return int.from_bytes(rom[offset : offset + 2], "little") if offset + 2 <= len(rom) else 0


def u32(rom: bytes, offset: int) -> int:
    return int.from_bytes(rom[offset : offset + 4], "little") if offset + 4 <= len(rom) else 0


def s32(rom: bytes, offset: int) -> int:
    return int.from_bytes(rom[offset : offset + 4], "little", signed=True) if offset + 4 <= len(rom) else 0


def pointer(rom: bytes, offset: int) -> int:
    return u32(rom, offset)


def pointer_offset(rom: bytes, offset: int) -> int | None:
    return gba_pointer_to_offset(pointer(rom, offset), len(rom))


@dataclass(frozen=True)
class MapLayout:
    offset: int
    width_blocks: int
    height_blocks: int
    border_offset: int | None
    map_offset: int
    primary_tileset_offset: int
    secondary_tileset_offset: int

    @property
    def width(self) -> int:
        return self.width_blocks * MAP_METATILE_SIZE

    @property
    def height(self) -> int:
        return self.height_blocks * MAP_METATILE_SIZE


@dataclass(frozen=True)
class TilesetResource:
    offset: int
    is_compressed: bool
    tile_data: bytes
    palettes: list[list[tuple[int, int, int, int]]]
    metatile_offset: int


@dataclass(frozen=True)
class RenderedMap:
    width: int
    height: int
    rgba: bytes


def decompress_lz77_10(rom: bytes, offset: int) -> bytes:
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


def decode_bgr555(color: int, alpha: int = 255) -> tuple[int, int, int, int]:
    r5 = color & 0x1F
    g5 = (color >> 5) & 0x1F
    b5 = (color >> 10) & 0x1F
    return (r5 * 255 // 31, g5 * 255 // 31, b5 * 255 // 31, alpha)


def decode_palette_banks_16(rom: bytes, offset: int, bank_count: int = 16) -> list[list[tuple[int, int, int, int]]]:
    if not valid_offset(offset, rom, bank_count * 16 * 2):
        raise ValueError(f"调色板越界：0x{offset:08X}")
    palettes = []
    for bank in range(bank_count):
        colors = []
        for color_index in range(16):
            color_offset = offset + (bank * 16 + color_index) * 2
            colors.append(decode_bgr555(u16(rom, color_offset)))
        palettes.append(colors)
    return palettes


def decode_4bpp_tiled_pixels(data: bytes, width: int, height: int) -> bytes:
    tile_bytes = 32
    tiles_per_row = width // MAP_TILE_SIZE
    max_tiles = tiles_per_row * (height // MAP_TILE_SIZE)
    tiles = min(len(data) // tile_bytes, max_tiles)
    pixels = bytearray(width * height)
    for tile_index in range(tiles):
        tile_base = tile_index * tile_bytes
        tile_x = tile_index % tiles_per_row
        tile_y = tile_index // tiles_per_row
        for row in range(MAP_TILE_SIZE):
            row_base = tile_base + row * 4
            y = tile_y * MAP_TILE_SIZE + row
            pixel_base = y * width + tile_x * MAP_TILE_SIZE
            for col_pair in range(4):
                value = data[row_base + col_pair]
                pixels[pixel_base + col_pair * 2] = value & 0x0F
                pixels[pixel_base + col_pair * 2 + 1] = (value >> 4) & 0x0F
    return bytes(pixels)


def read_map_layout(rom: bytes, layout_offset: int, layout_size: int = 0x18) -> MapLayout:
    if not valid_offset(layout_offset, rom, layout_size):
        raise ValueError(f"MapLayout 越界：0x{layout_offset:08X}")
    width_blocks = s32(rom, layout_offset)
    height_blocks = s32(rom, layout_offset + 4)
    map_offset = pointer_offset(rom, layout_offset + 12)
    primary_tileset_offset = pointer_offset(rom, layout_offset + 16)
    secondary_tileset_offset = pointer_offset(rom, layout_offset + 20)
    if width_blocks <= 0 or height_blocks <= 0:
        raise ValueError(f"MapLayout 尺寸非法：0x{layout_offset:08X}")
    if map_offset is None or primary_tileset_offset is None or secondary_tileset_offset is None:
        raise ValueError(f"MapLayout 指针非法：0x{layout_offset:08X}")
    return MapLayout(
        offset=layout_offset,
        width_blocks=width_blocks,
        height_blocks=height_blocks,
        border_offset=pointer_offset(rom, layout_offset + 8),
        map_offset=map_offset,
        primary_tileset_offset=primary_tileset_offset,
        secondary_tileset_offset=secondary_tileset_offset,
    )


def read_map_tileset(rom: bytes, tileset_offset: int) -> TilesetResource:
    if not valid_offset(tileset_offset, rom, 24):
        raise ValueError(f"tileset 指针非法：0x{tileset_offset:08X}")
    tiles_offset = pointer_offset(rom, tileset_offset + 4)
    palette_offset = pointer_offset(rom, tileset_offset + 8)
    metatile_offset = pointer_offset(rom, tileset_offset + 12)
    if tiles_offset is None or palette_offset is None or metatile_offset is None:
        raise ValueError(f"tileset 资源指针非法：0x{tileset_offset:08X}")
    if not valid_offset(palette_offset, rom, 16 * 16 * 2) or not valid_offset(metatile_offset, rom, TILESET_METATILE_COUNT * 16):
        raise ValueError(f"tileset 资源越界：0x{tileset_offset:08X}")
    is_compressed = bool(rom[tileset_offset])
    tile_data = decompress_lz77_10(rom, tiles_offset) if is_compressed else rom[tiles_offset : min(len(rom), tiles_offset + 0x4000)]
    return TilesetResource(
        offset=tileset_offset,
        is_compressed=is_compressed,
        tile_data=tile_data,
        palettes=decode_palette_banks_16(rom, palette_offset),
        metatile_offset=metatile_offset,
    )


def render_map_layout(rom: bytes, layout: MapLayout, max_pixels: int = DEFAULT_MAX_MAP_PIXELS) -> RenderedMap:
    if layout.width * layout.height > max_pixels:
        raise ValueError(f"地图过大，暂不渲染：{layout.width}x{layout.height}")
    if not valid_offset(layout.map_offset, rom, layout.width_blocks * layout.height_blocks * 2):
        raise ValueError(f"地图 block 数据越界：0x{layout.map_offset:08X}")
    primary = read_map_tileset(rom, layout.primary_tileset_offset)
    secondary = read_map_tileset(rom, layout.secondary_tileset_offset)
    canvas = bytearray([0, 0, 0, 255] * (layout.width * layout.height))
    for block_y in range(layout.height_blocks):
        for block_x in range(layout.width_blocks):
            block_offset = layout.map_offset + (block_y * layout.width_blocks + block_x) * 2
            block_id = u16(rom, block_offset) & 0x03FF
            draw_metatile(rom, canvas, layout.width, layout.height, primary, secondary, block_id, block_x, block_y)
    return RenderedMap(width=layout.width, height=layout.height, rgba=bytes(canvas))


def tile_color_index(tile_data: bytes, tile_id: int, x: int, y: int) -> int:
    offset = tile_id * 32 + y * 4 + x // 2
    if offset >= len(tile_data):
        return 0
    value = tile_data[offset]
    return (value >> 4) & 0x0F if x & 1 else value & 0x0F


def draw_pixel(canvas: bytearray, width: int, height: int, x: int, y: int, rgba: tuple[int, int, int, int]) -> None:
    if not (0 <= x < width and 0 <= y < height):
        return
    offset = (y * width + x) * 4
    canvas[offset : offset + 4] = bytes(rgba)


def draw_tile(canvas: bytearray, width: int, height: int, primary: TilesetResource, secondary: TilesetResource, entry: int, dst_x: int, dst_y: int, upper_layer: bool) -> None:
    tile_id = entry & 0x03FF
    horizontal_flip = bool(entry & 0x0400)
    vertical_flip = bool(entry & 0x0800)
    palette_bank = (entry >> 12) & 0x0F
    tileset = secondary if tile_id >= TILESET_METATILE_COUNT else primary
    local_tile = tile_id - TILESET_METATILE_COUNT if tile_id >= TILESET_METATILE_COUNT else tile_id
    palette = tileset.palettes[palette_bank]
    for pixel_y in range(MAP_TILE_SIZE):
        source_y = MAP_TILE_SIZE - 1 - pixel_y if vertical_flip else pixel_y
        for pixel_x in range(MAP_TILE_SIZE):
            source_x = MAP_TILE_SIZE - 1 - pixel_x if horizontal_flip else pixel_x
            color_index = tile_color_index(tileset.tile_data, local_tile, source_x, source_y)
            if upper_layer and color_index == 0:
                continue
            draw_pixel(canvas, width, height, dst_x + pixel_x, dst_y + pixel_y, palette[color_index])


def draw_metatile(rom: bytes, canvas: bytearray, width: int, height: int, primary: TilesetResource, secondary: TilesetResource, block_id: int, block_x: int, block_y: int) -> None:
    tileset = secondary if block_id >= TILESET_METATILE_COUNT else primary
    local_id = block_id - TILESET_METATILE_COUNT if block_id >= TILESET_METATILE_COUNT else block_id
    metatile_offset = tileset.metatile_offset + local_id * 16
    entries = [u16(rom, metatile_offset + index * 2) for index in range(8)]
    positions = ((0, 0), (8, 0), (0, 8), (8, 8))
    base_x = block_x * MAP_METATILE_SIZE
    base_y = block_y * MAP_METATILE_SIZE
    for layer in range(2):
        for index, (offset_x, offset_y) in enumerate(positions):
            draw_tile(canvas, width, height, primary, secondary, entries[layer * 4 + index], base_x + offset_x, base_y + offset_y, layer == 1)
