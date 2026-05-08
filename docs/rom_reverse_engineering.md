# 三代改版 ROM 逆向分层

这个工程现在把 ROM 知识分成三层：

1. **通用三代格式层**：GBA 指针、LZ77 `0x10` 解压、4bpp tile、BGR555 调色板、16x16 metatile、MapLayout 渲染。
2. **ROM profile 层**：某个具体 ROM 的表位置、结构变体、脚本命令长度、特殊变量和 special id。
3. **业务导出层**：把 profile 和通用解析器组合成字典、Encounter、地图预览、合法性规则等用户可见数据。

通用层代码位于 `editor/gen3_rom.py`。当前 ROM 的 profile 位于 `editor/rom_profiles.py`。

## 通用识别符

后续不要优先用“地址本身”描述知识，优先用下面这类识别符：

| 识别符 | 含义 | 识别方法 |
| --- | --- | --- |
| `species_name_table.primary` | 宝可梦定长名称表 | 定长文本项，可被当前字库解码，数量与 species 槽一致 |
| `move_name_table.primary` | 招式定长名称表 | 定长文本项，和 move data / PP 表 id 对齐 |
| `move_name_table.extension` | 招式扩展名称表 | hack 扩容后的定长文本表，从 extension start 接续 |
| `ability_name_table.primary` | 特性定长名称表 | 定长文本项，和 base stats ability id 关联 |
| `ability_name_table.extension` | 特性扩展名称表 | hack 扩容后的特性名表 |
| `base_stats_table` | 种族基础数据表 | 每 species 固定 28 字节，含 type/gender/growth/ability/wild item |
| `wild_encounter_headers.active` | 当前野生表头 | `map_group/map_number + 4 个 encounter info 指针`，以 `FF FF` 结束 |
| `map_groups.active` | 当前地图组指针表 | 指向 map header pointer list，首项能通过 MapHeader 合法性检查 |
| `region_map_entries` | 区域地图名/坐标表 | `name pointer + x/y/w/h`，region map section id 索引 |
| `script_command_lengths` | 当前脚本命令长度表 | 控制流解析需要的 opcode -> byte length |
| `script_special_battle` | 由脚本变量触发的定点战斗 | `setvar species/level/item` 后调用 start-battle special |
| `in_game_trade_table` | NPC 交换表 | `setvar trade_index` 后调用 trade special，index 指向记录 |
| `front_sprite_table` | 宝可梦正面图表 | 每 species 一个 sprite pointer，通常 LZ77 压缩 |
| `normal_palette_table` | 普通调色板表 | 每 species 一个 palette pointer |
| `shiny_palette_table` | 闪光调色板表 | 每 species 一个 palette pointer |

地址只是某个 profile 对这些识别符的绑定。例如当前 BW 版本里 `wild_encounter_headers.active = 0xEA2D34`，但其他改版 ROM 应该重新定位这个识别符，而不是复用地址。

## 当前 ROM Profile

当前 profile id 是 `pokemon_emerald_ex_bw`，标签是 `漆黑的魅影 5.0EX BW`。

核心 profile 信息在 `CURRENT_ROM_PROFILE` 中集中维护：

- `name_tables`：species/move/ability 名称表和扩展表。
- `items`：道具记录结构。
- `creature_data`：base stats、升级招式、进化、蛋招式、TM/HM、教学招式。
- `wild_encounters`：当前/旧野生表头候选。
- `maps`：地图组、region map、MapHeader/MapLayout/Event/Connection 结构。
- `scripts`：脚本命令长度、定点战斗 special、交换 special、交换表结构。
- `sprites`：宝可梦贴图和调色板表。

旧的常量名仍保留在 `rom_data.py` 和 `pokemon_save_core.py`，用于兼容现有测试和调用；但这些常量现在应视为 `CURRENT_ROM_PROFILE` 的展开结果。

## 反解其他三代改版 ROM 的流程

1. **确认基础身份**

   读取 ROM header 的 title/game code/maker code，同时计算全 ROM SHA-256。header 只能做弱识别，hash 才适合发布校验。

2. **定位文本和基础数据**

   从名称表、base stats、move data 等高置信结构开始。优先用定长记录、可解码字符、id 范围、交叉引用关系评分，而不是只靠固定地址。

3. **定位野生表和地图表**

   野生表用 header 连续合法性评分：map group/number 合理，encounter info 指针合法，slot 数和等级/species 合理。

   地图表用 MapHeader 合法性评分：layout/events/scripts/connections 指针能落在 ROM 内，layout 宽高和 tileset 指针合理。

4. **定位脚本来源**

   先建立 opcode 长度表和控制流跟随规则。Encounter 必须来自 MapHeader 关联脚本入口，或来自能按命令边界完整解析的本地 encounter 子段。

5. **定位 native special 表**

   交换、游走、菜单、谜题等不要直接硬编码 ref 文本。必须先逆到脚本变量、special id、表结构或 ARM/Thumb 证据。

6. **生成 profile**

   把定位结果写成新的 `RomProfile`，再用同一套通用导出层生成字典、Encounter 和资源包。

## 发布建议

发布给其他用户时，不建议依赖用户本地 ROM 即时解析。更稳的形态是：

- 构建期用指定 ROM 生成资源包：字典、Encounter、合法性规则、贴图、地图预览、manifest。
- manifest 记录 profile id、ROM SHA-256、header 信息、资源 schema version。
- 运行期默认只读资源包，不需要 ROM。
- 用户提供 ROM 时先校验 hash；不匹配时禁用或降级 ROM 相关功能，而不是静默解析。

这样当前 BW 版本只是 `pokemon_emerald_ex_bw` 这个 profile 的子产物；未来要支持其他三代改版 ROM，只需要新增 profile 和必要的识别器，不需要重写存档编辑器。
