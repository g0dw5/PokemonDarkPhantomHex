# 漆黑的魅影 Web 存档修改器

macOS 自带 Python 3 即可运行，不依赖第三方库。工具默认读取本机：

- ROM：`/Users/wang.song/Desktop/pokemon/漆黑的魅影 5.0EX BW.gba`
- 存档：`/Users/wang.song/Desktop/pokemon/漆黑的魅影 5.0EX BW.sav`

## 运行

```bash
python3 editor/web_save_editor.py
```

也可以双击 `run_editor.command`。如果 macOS 阻止双击运行，先在终端执行：

```bash
chmod +x run_editor.command
```

## 功能

- 自动加载 `/Users/wang.song/Desktop/pokemon/漆黑的魅影 5.0EX BW.sav`
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

这个工具按《宝可梦 绿宝石》系 128KB `.sav` 结构处理。《漆黑的魅影 5.0EX BW.gba》的 ROM 头是 `POKEMON EMER`，当前存档也符合该结构。

改完保存后，先完全关闭模拟器里的游戏或确认模拟器不会覆盖电池存档，再重新载入 `.sav`。如果游戏内不生效，通常是模拟器还握着旧存档。

## ROM 与存档规格记忆

以下规则来自当前工程对 `/Users/wang.song/Desktop/pokemon/漆黑的魅影 5.0EX BW.gba` 和对应 128KB `.sav` 的逆向验证，用于后续实现特性、性别、招式合法性约束。

### 存档里直接存储的宝可梦字段

队伍宝可梦使用三代 GBA 结构。存档只保存当前状态，不保存“该宝可梦理论上能学什么技能”这类约束集合。

- `species`：存于 Growth 子结构 `+0`，`u16`。
- 当前 4 个招式：存于 Attacks 子结构 `+0..+7`，4 个 `u16 move_id`。
- 当前 4 个 PP：存于 Attacks 子结构 `+8..+11`，4 个 `u8`。
- `ability_bit`：存于 Misc 子结构 IV word 的 bit 31，不直接存 ability id。
- 蛋标记：存于 Misc 子结构 IV word 的 bit 30。
- IV：同一个 IV word 内，每项 5 bits。
- 性格：不是独立字段，使用 `personality % 25`。
- 性别：不是独立字段，由 ROM 中 species 性别比例和 PID 低 8 位计算。
- 闪光：不是独立字段，由 OT ID 和 PID 计算。

`editor/pokemon_save_core.py` 已实现子结构解密、重排、checksum、`ability_bit`、性别、性格和闪光的读写逻辑。

### ROM 名称全集表

名称表只用于展示全集枚举和反查名称，不代表每个 species 的合法子集。

- species 名称：`0x3185C8`，定长 11 bytes，当前解析 412 个。
- move 名称：`0x31977C`，定长 13 bytes；扩展 move 从 `0x1903207` 起；当前解析 472 个。
- ability 名称：`0x31B6DB`，定长 13 bytes；扩展 ability 从 `0x1C00000` 起；当前解析 151 个。
- item 名称：`0x5839A0`，每项 44 bytes，名称 14 bytes；当前解析 377 个。

这些 offset 目前定义在 `editor/rom_data.py`。

### ROM 种族基础数据表

species 的性别比例和特性子集在 base stats 表中。

- base stats offset：`0x3203CC`
- record size：`28` bytes
- species N 的记录：`0x3203CC + N * 28`
- `+16`：性别比例 byte
- `+22`：第一特性 ability id
- `+23`：第二特性 ability id

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

### ROM 升级技能表

升级技能表保存每个 species 的升级学会技能。

- 指针表 offset：`0x329378`
- species 0 是占位。
- 当前 ROM 的升级技能指针索引相对 species/base stats/TMHM 多 1 格偏移。
- species N 的 learnset 指针在 `0x329378 + (N + 1) * 4`。
- 指针是 GBA ROM 指针，需减 `0x08000000` 得到文件 offset。
- 每条记录是 `u16`：`(level << 9) | move_id`。
- `move_id = value & 0x01FF`。
- `level = value >> 9`。
- `0xFFFF` 表示该 species learnset 结束。

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

当前存档样例验证：

- 玛力露丽的 `冲浪术/怪力术/碎岩术` 命中 TM/HM，`泡沫` 命中当前等级内升级技能。
- 盔甲鸟的 4 个技能都命中 TM/HM。
- 2026-05-06 复核：升级技能表不能按 `species_id` 直接索引，否则 `species 243 雷公` 会读到类似幸福蛋的升级表；TM/HM 位图按 `species_id` 索引是正确的。当前实现已只对升级技能表使用 `species_id + 1`。
