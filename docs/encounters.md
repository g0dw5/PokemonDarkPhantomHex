# Encounter 逆向说明

本项目的 Encounter 只展示能从当前 ROM 直接证明的来源。绿宝石原版机制、攻略资料或通用宝可梦知识不能单独作为当前改版 ROM 的 Encounter 依据。

## 数据来源

### 普通野生表

来源：活动野生 Encounter header table。

- 当前 ROM 活动表：`0xEA2D34`
- 旧表：`0x552D48`，内容较旧，解析时不作为活动来源
- header size：`20` bytes
- 结束标记：header 前两个字节为 `FF FF`

单条 header：

| 偏移 | 字段 | 说明 |
| --- | --- | --- |
| `+0` | `map_group u8` | 地图组 |
| `+1` | `map_number u8` | 地图号 |
| `+2` | padding `u16` | 当前为 0 |
| `+4` | land pointer | 草丛 EncounterInfo |
| `+8` | water pointer | 冲浪 EncounterInfo |
| `+12` | rock smash pointer | 碎岩 EncounterInfo |
| `+16` | fishing pointer | 钓鱼 EncounterInfo |

EncounterInfo：

| 偏移 | 字段 |
| --- | --- |
| `+0` | `rate u32` |
| `+4` | `wild_list pointer` |

wild list 每项 4 bytes：`min_level u8`、`max_level u8`、`species u16`。

UI 里的 `rate` 是按槽位权重聚合后的百分比，分母为 `100`。同一地图同一方式下，所有 species 的 `rate` 加和应为 `100%`。原始地图触发率保存在 `encounter_rate`。

槽位权重：

| 方式 | 槽位权重 |
| --- | --- |
| 草丛 | `20,20,10,10,10,10,5,5,4,4,1,1` |
| 冲浪 | `60,30,5,4,1` |
| 碎岩 | `60,30,5,4,1` |
| 旧钓竿 | `70,30`，对应钓鱼槽位 `1..2` |
| 好钓竿 | `60,20,20`，对应钓鱼槽位 `3..5` |
| 超级钓竿 | `40,40,15,4,1`，对应钓鱼槽位 `6..10` |

普通野生表的 land/water 指针会按当前地图头修正 UI 方式名：`MapHeader +0x17 map_type == 4` 的 land 表显示为“山洞”；水下 map key 或 `map_type == 5` 的 water 表显示为“潜水”。这些只是展示名修正，原始槽位权重仍按 ROM 表类型解析。

### ROM 脚本来源

脚本来源来自 MapHeader 关联的 object event、coord event、bg event 和 map script 指针。扫描边界使用所有地图脚本 target 的全局偏移：单个脚本最多扫描 `768` bytes，并在遇到下一个脚本 target 前截断，避免把连续脚本里的命令误归属到前一个对象。

支持的脚本来源：

| source_type | method | 证据 |
| --- | --- | --- |
| `static` | 定点 | `0xB6 setwildbattle species level item` |
| `gift` | 赠送 | `0x79 givepokemon species level item...` |
| `egg` | 蛋 | `0x7A giveegg species` |
| `script_special` | 特殊事件 | 同一 setvar 段内 `setvar 0x8004=species`、`setvar 0x8005=level`、可选 `setvar 0x8006=item`，然后 `special 0x01E2` |

脚本来源没有概率字段。

脚本命令必须从 MapHeader 关联的脚本入口按控制流可达，才会被纳入 Encounter。解析器会跟随脚本内的 `call`、`goto`、条件跳转和已知 trainer battle 后续脚本指针，也会按固定长度跨过常见消息命令；不会再把扫描窗口里“看起来像 `givepokemon`”的字节序列当作赠送来源。

`script_special` 必须满足两个约束：

- `0x8004 species` 与 `special 0x01E2` 在同一段内。
- 如果在 `special 0x01E2` 前出现新的 `setvar 0x8004`，前一个 species 不算 Encounter。

这条规则用于避免跨段误判。例如当前 ROM `0x2691AA`：

```text
16 04 80 03 00    setvar 0x8004 = 0x0003 妙蛙花
16 05 80 23 00    setvar 0x8005 = 0x0023 Lv35
25 fd 01          special 0x01FD
...
16 04 80 fa 00    setvar 0x8004 = 0x00FA 凤王
16 05 80 46 00    setvar 0x8005 = 0x0046 Lv70
16 06 80 00 00
25 e2 01          special 0x01E2
```

妙蛙花后接的是 `special 0x01FD`，不是 Encounter；凤王后接 `special 0x01E2`，是 Encounter。

### special_case 来源

`special_case` 只用于当前 ROM 中不能由野生表或地图脚本表达、但机制明确的来源。当前仅保留：

| species | method | 地图 | 说明 |
| --- | --- | --- | --- |
| `328 笨笨鱼` | 特殊垂钓 | `0-34 119号道路` | 笨笨鱼水格钓鱼，命中水格时绕过普通钓鱼列表；显示为 Lv20-25，50% |

其他标准三代事件不能写入 `special_case`。如果要加入游走、交换、菜单或其他 native special，必须先逆向到当前 ROM 的表、脚本或 ARM/Thumb 代码证据。

## Encounter 字段

每条 Encounter 至少应包含：

| 字段 | 说明 |
| --- | --- |
| `source_type` | 来源类型，例如 `wild`、`static`、`script_special` |
| `method` | UI 展示方式，例如 草丛、定点、特殊事件 |
| `map_group` / `map_number` / `map_id` | 地图定位；无固定地图的来源必须明确说明 |
| `location` | UI 地图名 |
| `min_level` / `max_level` | 等级范围 |
| `rate` | 仅普通野生表或特殊机制有概率 |
| `encounter_rate` | 普通野生表的地图触发率 |
| `script_offset` | 脚本来源的 ROM offset |
| `script_source` / `script_source_index` | object、coord、bg 或 map_script 的来源位置 |
| `source_note` | 证据说明 |

`script_special` 还应带：

| 字段 | 当前值 |
| --- | --- |
| `species_var` | `0x8004` |
| `level_var` | `0x8005` |
| `item_var` | `0x8006` |
| `special_id` | `0x01E2` |

## 当前 ROM 核对样例

| species | 结果 |
| --- | --- |
| `3 妙蛙花` | 无 Encounter；`0x2691AA` 是 `special 0x01FD`，不算特殊战 |
| `20 拉达` | 无 Encounter；未在普通野生表、定点、特殊战、赠送或蛋来源中找到 |
| `1 妙蛙种子` | 101号道路，草丛 Lv5；暮水镇，赠送 Lv55；源初之山，定点 Lv2 |
| `151 梦幻` | 遥远的孤岛，特殊事件 Lv30，`script_special` |
| `249 洛奇亚` | 神之领域，特殊事件 Lv70；灾难船舱，定点 Lv70 |
| `250 凤王` | 神之领域，特殊事件 Lv70 |
| `251 雪拉比` | 时之森，定点 Lv30 |
| `267 克蕾赛丽亚` | 新月岛，定点 Lv50 |
| `268 达克莱伊` | 新月岛 / 满月岛，定点 Lv50 |
| `273 洁咪` | 断空瀑布 / 花之海，定点 Lv30 |
| `274 阿尔修斯` | 创世神殿，定点 Lv100 |
| `326 索罗亚` | 幻影之森，赠送 Lv5；幻影之森，定点 Lv5 |
| `327 索罗亚克` | 魅影之森，定点 Lv35 |
| `385 漂浮泡泡` | 天气研究所 2F，赠送 Lv25；120号道路，草丛 Lv25-27 |
| `398 铁哑铃` | 绿岭市 大吾家，赠送 Lv5；卡绿隧道，山洞 Lv8 |
| `404 海皇牙` | 海之窟 End，定点 Lv70 |
| `405 古拉顿` | 陆之窟 End，定点 Lv70 |
| `406 裂空座` | 天空之柱 Top，定点 Lv70 |
| `407 拉帝亚斯` | 南方小岛 Interior，特殊事件 Lv50 |
| `408 拉帝欧斯` | 南方小岛 Interior，特殊事件 Lv50 |
| `410 迪奥西斯` | 诞生之岛，特殊事件 Lv50 |

## 不纳入的来源

- 进化来源不属于 Encounter。
- 原版/攻略中的事件，如果不能从当前 ROM 解析出证据，不展示。
- 游走来源暂不展示；需要先逆向当前 ROM 的 roamer species 选择、等级和地图范围。
- 对战设施、菜单、交换、商店、装饰品等 special 不应因为出现 species id 就被当成 Encounter。
