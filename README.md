# 漆黑的魅影 Web 存档修改器

macOS 自带 Python 3 即可运行，不依赖第三方库。页面启动后点击“打开/加载”选择 `.sav` 存档文件。

ROM 路径不写死在工程里。加载 `xxx.sav` 时，工具会自动搜索同目录下的同名 `xxx.gba`，用于特性、性别、招式和 PP 等 ROM 约束数据；如果找不到同名 ROM，仍可查看和编辑存档，但会跳过依赖 ROM 的合法性检查。

## 运行

```bash
python3 editor/web_save_editor.py
```

也可以双击 `run_editor.command`。如果 macOS 阻止双击运行，先在终端执行：

```bash
chmod +x run_editor.command
```

## 功能

- 通过页面“打开/加载”选择并加载 `.sav` 存档
- 识别三代 GBA 轮换存档槽，并选择当前有效槽
- 修改背包内各口袋的道具 ID 和数量
- 修改队伍宝可梦的种族、携带道具、经验、亲密度、等级、HP、招式、PP、努力值、个体值、特性位和蛋标记
- 修改盒子宝可梦的种族、携带道具、性格、性别、特性位、招式、PP、努力值、个体值和蛋标记
- 队伍/盒子宝可梦修改页会按当前 species/level 从 ROM 约束生成性别、特性和招式下拉；选择招式时会同步填入该招式默认 PP，仍可手动调整 PP
- 招式约束覆盖自身升级、前置形态升级、自身遗传、前置形态遗传和 TM/HM；当前等级还不能学的未来升级招式会在下拉中置灰
- 背包和携带道具展示 TM/HM 时会追加对应技能名
- 提供 ROM 名称/字码录入校正页面，校正结果写入 `data/rom_text.json`
- 重算宝可梦数据 checksum 和存档 section checksum
- 保存前自动创建 `.bak-时间戳.sav` 备份
- 校验存档 section、队伍宝可梦 checksum、等级、EV/IV、HP 等基础合法性

## 注意

这个工具按《宝可梦 绿宝石》系 128KB `.sav` 结构处理。《漆黑的魅影 5.0EX BW.gba》的 ROM 头是 `POKEMON EMER`，已验证样例 `.sav` 符合该结构。

改完保存后，先完全关闭模拟器里的游戏或确认模拟器不会覆盖电池存档，再重新载入 `.sav`。如果游戏内不生效，通常是模拟器还握着旧存档。

## ROM 与存档规格记忆

以下规则来自当前工程对《漆黑的魅影 5.0EX BW》ROM 和对应 128KB `.sav` 的逆向验证，用于后续实现特性、性别、招式合法性约束。

### 宝可梦存档结构

队伍和盒子都使用三代 GBA 宝可梦结构。存档只保存个体当前数据，不保存“该 species 合法能学什么招式/特性/性别”这类约束集合；约束来自 ROM 表。

队伍数据：

- 位置：当前有效存档槽的 section 1。
- 队伍数量：section 1 data `0x0234`，`u32`，最多 6。
- 队伍记录：section 1 data `0x0238 + slot_index * 100`，每只 100 bytes；`slot_index` 为 `0..count-1`。
- 前 80 bytes 与盒子宝可梦完全同构。
- 额外 20 bytes 是队伍实时字段；包含异常状态、等级、当前 HP 和战斗能力值。
- 当前 Web 只写队伍额外字段中的 `level`；当前 HP 和能力值不会重算写入。

队伍 100 bytes 记录中的额外字段：

| 偏移 | 字段 |
| --- | --- |
| `0x50` | `status_condition u32` |
| `0x54` | `level u8` |
| `0x56` | `current_hp u16` |
| `0x58` | `max_hp u16` |
| `0x5A` | `attack u16` |
| `0x5C` | `defense u16` |
| `0x5E` | `speed u16` |
| `0x60` | `sp_attack u16` |
| `0x62` | `sp_defense u16` |

`status_condition` 是队伍内宝可梦的异常状态位字段，盒子 80 bytes 结构没有这个字段。常见位含义：

| bits | 含义 |
| --- | --- |
| `0..2` | 睡眠剩余回合 |
| `3` | 中毒 |
| `4` | 烧伤 |
| `5` | 冰冻 |
| `6` | 麻痹 |
| `7` | 剧毒 |

盒子数据：

- 位置：PC storage 跨 section 5..13 拼接。
- storage 前 4 bytes 不是宝可梦记录；宝可梦数据从拼接 storage `+4` 开始。
- 盒子容量：14 个盒子，每盒 30 格，共 420 格。
- 盒子记录：`4 + ((box - 1) * 30 + (slot - 1)) * 80`，每只 80 bytes。
- 盒子记录没有队伍的额外实时字段；等级由 Growth 子结构里的 `experience` 和 species base stats `growth_rate` 反推。当前 HP、能力值不直接存为独立字段。

队伍和盒子共享的 80 bytes 个体结构：

| 偏移 | 字段 | 说明 |
| --- | --- | --- |
| `0x00` | `personality` / PID, `u32` | 决定子结构顺序、性格、性别判定输入、闪光判定输入 |
| `0x04` | `ot_id`, `u32` | 训练家 ID/里 ID 合并值；参与加密 key 和闪光判定 |
| `0x08..0x1B` | 昵称、语言、标记、OT 名等 | 当前工具保留原字节，不作为主要编辑字段 |
| `0x1C` | checksum, `u16` | 对解密后的 48 bytes 子结构按 `u16` 求和 |
| `0x1E` | padding, `u16` | 保留 |
| `0x20..0x4F` | 加密子结构 | 含两端共 48 bytes，即半开区间 `[0x20, 0x50)`；由 4 个 12 bytes 子结构组成，顺序由 `personality % 24` 决定，按 `personality ^ ot_id` 加解密 |

4 个加密子结构：

| 子结构 | 当前使用字段 |
| --- | --- |
| Growth | `+0 species u16`，`+2 held_item u16`，`+4 experience u32`，`+9 friendship u8` |
| Attacks | `+0..+7 moves[4] u16`，`+8..+11 pps[4] u8` |
| EVs/Condition | `+0..+5 evs[HP, Atk, Def, Speed, SpAtk, SpDef] u8`；华丽大赛状态当前保留 |
| Misc | `+2 origin_word u16` 中 `bit 11..14` 为捕获球；`+4 iv_word u32` 中 6 项 IV 每项 5 bits，`bit 30` 为蛋标记，`bit 31` 为 `ability_bit` |

派生字段和写入规则：

- `ability_id` 不直接存档，只存 `ability_bit`；实际特性由 ROM base stats 的第一/第二特性推导。
- 盒子等级不是独立字段；由 `species -> growth_rate` 与 `experience` 计算。队伍记录额外保存的 `level` 是实时缓存字段。
- 性格不是独立字段，使用 `personality % 25`。
- 性别不是独立字段，由 ROM species 性别比例和 PID 低 8 位计算。
- 闪光不是独立字段，由 `ot_id` 和 PID 计算。
- 修改性格、性别或闪光时，需要搜索并改写 PID，同时保持目标约束。
- 修改加密子结构后必须重建子结构顺序、重新加密、重算宝可梦 checksum，并重算所在 save section checksum。

### ROM 名称全集表

名称表只用于展示全集枚举和反查名称，不代表每个 species 的合法子集。

- species 名称：`0x3185C8`，定长 11 bytes，当前解析 412 个。
- move 名称：`0x31977C`，定长 13 bytes；扩展 move 从 `0x1903207` 起；当前解析 472 个。
- ability 名称：`0x31B6DB`，定长 13 bytes；扩展 ability 从 `0x1C00000` 起；当前解析 151 个。
- item 名称：`0x5839A0`，每项 44 bytes，名称 14 bytes；当前解析 377 个。

这些 offset 目前定义在 `editor/rom_data.py`。

### ROM 种族基础数据表

species 的基础数据在 ROM base stats 表中。当前工具主要使用其中的性别比例和特性字段，但同一条 28 bytes 记录还包含基础能力、属性、经验类型等信息。

- base stats offset：`0x3203CC`
- record size：`28` bytes
- species N 的记录：`0x3203CC + N * 28`

单条 species 记录格式：

| 偏移 | 字段 | 说明 |
| --- | --- | --- |
| `+0` | `base_hp u8` | 基础 HP |
| `+1` | `base_attack u8` | 基础攻击 |
| `+2` | `base_defense u8` | 基础防御 |
| `+3` | `base_speed u8` | 基础速度 |
| `+4` | `base_sp_attack u8` | 基础特攻 |
| `+5` | `base_sp_defense u8` | 基础特防 |
| `+6` | `type1 u8` | 第一属性 ID |
| `+7` | `type2 u8` | 第二属性 ID；单属性通常与 `type1` 相同 |
| `+8` | `catch_rate u8` | 捕获率 |
| `+9` | `exp_yield u8` | 击败后基础经验 |
| `+10` | `ev_yield u16` | 击败后努力值收益位字段 |
| `+12` | `item1 u16` | 野生携带道具 1 |
| `+14` | `item2 u16` | 野生携带道具 2 |
| `+16` | `gender_ratio u8` | 性别比例 |
| `+17` | `egg_cycles u8` | 孵化周期 |
| `+18` | `base_friendship u8` | 初始亲密度 |
| `+19` | `growth_rate u8` | 经验成长曲线 |
| `+20` | `egg_group1 u8` | 蛋组 1 |
| `+21` | `egg_group2 u8` | 蛋组 2 |
| `+22` | `ability1 u8` | 第一特性 ID |
| `+23` | `ability2 u8` | 第二特性 ID；为 0 时视为没有第二特性 |
| `+24` | `safari_flee_rate u8` | 狩猎区逃跑率 |
| `+25` | `body_color_flags u8` | 颜色/翻转标记等图鉴显示相关位 |
| `+26..+27` | padding / unused | 当前工具不使用 |

特性计算规则：

- 存档中只存 `ability_bit`。
- `ability_bit == 0` 使用 base stats `+22`。
- `ability_bit == 1` 且 base stats `+23 != 0` 时使用 `+23`。
- 如果第二特性为 `0`，即使 `ability_bit == 1` 也应回落到第一特性。

性别计算规则：

- `ratio == 255`：无性别。
- `ratio == 254`：固定雌性。
- `ratio == 0`：固定雄性。
- 其他值：`(personality & 0xFF) < ratio` 为雌，否则为雄。

编辑性别时不能直接写“性别字段”，需要调整 PID，并同时保持目标性格和闪光状态。现有 `adjust_personality()` 已按这个思路搜索可用 PID。

### ROM 可学招式数据来源

“宝可梦可学会招式”不是存档里的字段，也不是 ROM 里单独一张完整表。当前工具按 species 从多段 ROM 数据合成招式来源：

- 自身升级技能：来自升级技能指针表。
- 前置形态升级技能：先从进化表反查所有前置 species，再读取这些前置 species 的升级技能。
- 自身蛋招式：来自蛋招式线性表。
- 前置形态蛋招式：前置 species 的蛋招式也作为进化后可继承来源。
- TM/HM：来自 species TM/HM 可学位图，再映射到 TM/HM 编号对应的 move id。

存档中每只宝可梦只保存当前 4 个 `move_id` 和 4 个 PP；“这些 move 是否可学”完全由上述 ROM 表和当前等级推导。

当前判定口径：

- `move_id == 0` 表示空招式。
- 升级技能只有 `learn_level <= 当前等级` 时作为已学来源。
- `learn_level > 当前等级` 会作为未来可学来源提示，不算当前已学来源。
- 盒子宝可梦没有直接存储等级字段，当前 UI 会按经验值反推等级后生成约束；找不到 ROM 经验曲线时等级显示为未知。
- TM/HM 和蛋招式当前不区分获得时机，只要 species 表里命中就算可学来源。

### ROM 升级技能表

升级技能表保存每个 species 的升级学会技能。

- 指针表 offset：`0x329378`
- species 0 是占位。
- 当前 ROM 的升级技能指针索引相对 species/base stats/TMHM 多 1 格偏移。
- species N 的 learnset 指针在 `0x329378 + (N + 1) * 4`。
- 指针是 GBA ROM 指针，需减 `0x08000000` 得到文件 offset。
- learnset 内容是连续 `u16` 记录，直到 `0xFFFF` 结束。

单条升级技能记录格式：

| bits | 字段 | 说明 |
| --- | --- | --- |
| `0..8` | `move_id` | `value & 0x01FF`，当前 ROM 有效范围 `1..472` |
| `9..15` | `level` | `value >> 9`，当前按 `1..100` 校验 |

约束实现时可以区分：

- `level_up_now`：`level <= 当前等级` 的升级技能。
- `level_up_future`：该 species 未来等级会学，但当前等级还未学。

严格合法性通常只接受 `level_up_now`，宽松模式可把 `level_up_future` 作为警告而不是错误。

### ROM 进化表

进化表用于把进化型的合法招式扩展为“自身升级技能/遗传技能 + 所有前置形态升级技能/遗传技能”。

- evolution table offset：`0x32531C`
- 每 species 40 bytes，包含 5 个进化记录。
- 每个进化记录 8 bytes：`u16 method, u16 param, u16 target_species, u16 padding`。
- species N 的记录：`0x32531C + N * 40`
- 例：`species 306 蘑蘑菇` 的记录在 `0x3282EC`，内容 `04 00 17 00 33 01 00 00`，表示 Lv23 进化到 `species 307 斗笠菇`。
- 校验时会递归查找所有前置形态；例如斗笠菇自身学不会蘑菇孢子，但蘑蘑菇 Lv45 可学，所以 Lv50 斗笠菇携带蘑菇孢子应判定为合法来源 `前置蘑蘑菇Lv45`。
- 前置形态的遗传技能也会透传到后续形态，来源标记为 `前置<species>遗传`。
- 如果当前等级还达不到前置形态的学会等级，则 Web 下拉会显示该招式但置灰，例如 Lv40 斗笠菇的 `蘑菇孢子 [前置蘑蘑菇Lv45可学]`。

### ROM 蛋招式表

蛋招式表是线性表，不是指针表。

- egg move table offset：`0x32ADD8`
- species marker：`20000 + species_id`，即 `u16`。
- marker 后面连续的普通 move id 属于该 species。
- 下一个 marker 开始下一个 species。
- `0xFFFF` 表示整张蛋招式表结束。
- 当前 ROM 中可解析到 164 组 species 蛋招式。

注意：没有蛋招式 marker 的 species 应视为空集合。

### ROM TM/HM 表

TM/HM 由两部分组成：species 可学位图和 TM/HM 编号到 move id 的映射。

- TM/HM 道具 ID 范围：`0x0121..0x015A`，即 `技能机器01..秘传机器08`。
- TM/HM 道具记录仍在 item 表：`0x5839A0 + item_id * 44`；例如 `技能机器01` 在 `0x586B4C`。
- TM/HM 编号计算：`item_id - 0x0120`，所以 `0x0121` 是 1 号，`0x015A` 是 58 号。
- species TM/HM 可学位图 offset：`0x31E898`
- 每 species 8 bytes，覆盖 58 个 TM/HM 位。
- species N 的位图：`0x31E898 + N * 8`
- 位序是低位优先：第 `i` 个 TM/HM 检查 `bitmap[i // 8] & (1 << (i % 8))`。
- TM/HM 对应 move 表 offset：`0x1CA0000`
- move 表有 58 个 `u16 move_id`。

展开规则：

- 遍历 TM/HM index `0..57`。
- 如果 species 位图第 `index` 位为 1，则该 species 可学 `tmhm_move_table[index]`。
- UI 显示的 TM/HM 编号是 `index + 1`，例如 index 0 显示 `TM/HM01`。
- 背包道具 ID 到 TM/HM index 的换算是 `item_id - 0x0121`。

ROM 中还存在 `0x615B94` 和 `0x616040` 两个相同 TM/HM move 表副本，但已发现代码引用指向 `0x1CA0000`，后续实现应优先使用 `0x1CA0000`。

### ROM 树果编号

树果的游戏内 `NoXX` 不是背包格位，而是从 item id 推导。

- 树果道具 ID 范围：`0x0085..0x00AF`。
- 树果道具记录仍在 item 表：`0x5839A0 + item_id * 44`；例如 `蓝橘果` 是 item id `0x008B`，记录在 `0x585184`。
- 树果编号计算：`item_id - 0x0084`。所以 `蓝橘果 0x008B` 显示为 `No07`。

### 合法性约束实现

当前已在 `editor/pokemon_save_core.py` 中实现 ROM 约束层，集中暴露按 species 聚合后的约束：

```python
@dataclass(frozen=True)
class SpeciesConstraints:
    species_id: int
    ability_options: list[tuple[int, int]]  # [(ability_bit, ability_id)]
    gender_options: list[str]               # ["雄"], ["雌"], ["无性别"], or ["雄", "雌"]
    level_up_moves: dict[int, list[int]]    # move_id -> learned levels
    pre_evolution_level_up_moves: dict[int, dict[int, list[int]]]  # move_id -> pre_species_id -> learned levels
    egg_moves: set[int]
    pre_evolution_egg_moves: dict[int, set[int]]  # move_id -> pre_species_ids
    tmhm_moves: dict[int, int]              # move_id -> tmhm index, 1-based
```

当前校验策略：

- species：当前名称表和 base stats 主要覆盖 `1..412`，UI 层优先限制到这个范围。
- ability：只允许当前 species base stats `+22/+23` 推导出的有效 `ability_bit`。
- gender：按 ratio 限定可选项；固定性别或无性别 species 会被校验出来。
- moves：非 0 move 必须在 `1..472`；来源集合为 `level_up_now | pre_evolution_level_up_now | tmhm | egg | pre_evolution_egg` 时判定为已知合法。
- move 宽松模式：`level_up_future`、`pre_evolution_level_up_future`、定点教学、剧情赠送或 hack 特殊技能可能无法由上述三张表覆盖，当前先输出“可疑”校验信息，不阻止保存。
