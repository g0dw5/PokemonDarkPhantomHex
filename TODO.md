# TODO

这个文件作为 Codex 的任务队列使用。把想做的事写到「待处理」里；之后对 Codex 说「继续 TODO」或「处理 TODO」，Codex 会按本文件连续推进，直到没有可执行任务或遇到需要你介入的阻塞。

## 处理规则

- 默认处理「待处理」里最靠上的未完成任务。
- 如果任务有优先级，按 `P0`、`P1`、`P2`、`P3` 排序；同优先级按出现顺序处理。
- 一次「处理 TODO」指令表示允许 Codex 连续处理任务队列，不需要每完成一项就停下来等下一条指令。
- Codex 每次开始前先读取最新 `TODO.md` 和 `git status`。
- Codex 每次只从队列头部取出一项执行；该项完成、测试通过并提交后，再重新读取最新 `TODO.md` 和 `git status`，继续取下一项。
- Codex 会把正在做的任务移动到「进行中」，完成后移动到「已完成」。
- 需要用户决定、缺少文件、风险过高或验收条件不清楚时，移动到「阻塞」并写明原因。
- 如果遇到阻塞，只停止当前无法推进的任务；若「待处理」里还有其他不依赖该阻塞的任务，继续处理下一项。
- 只有当所有待处理任务都完成、全部剩余任务都阻塞，或下一步必须等待用户输入时，Codex 才停止 TODO 循环。
- TODO 执行模式下，每一项完成后必须先运行测试；测试通过后立即提交该项相关代码和 `TODO.md` 状态更新，再继续下一项。
- 如果某项测试失败，Codex 必须先修复并重跑测试；不能提交失败状态，除非你明确要求提交当前失败状态。
- 非 TODO 执行模式下，代码改动默认不自动提交；你明确说「提交」时再提交。
- TODO.md写入前要先读后写,以防我在写新任务手动保存的时候,被模型覆盖掉

## 任务格式

推荐格式：

```md
- [ ] P1 任务标题
  - 背景：为什么要做
  - 目标：完成后应达到什么效果
  - 验收：如何判断已经完成
  - 限制：不能做什么，或需要保留什么
```

简单任务也可以只写一行：

```md
- [ ] P2 修一下字典表搜索框样式
```

## 待处理

## 进行中

## 阻塞

## 已完成

- [x] P2 字典表-宝可梦里的Encounter发现一些名称跟跳转后的地图对不上的情况,比如 比雕 地图35-2 战羽鹰 天空之柱 3F,前者是我不希望出现的,后者是我认为比较好的,这样能在地图页面也更有区分度
  - 结果：地图实体名改为优先展示可区分楼层/房间的 map key 名称；扩展地图没有 map key 时使用 ROM region map 名，例如 `35-2` 展示为“启程之路”。
  - 结果：野生 Encounter 在地图实体抽取后回填同一套显示名和 `map_id`，字典表宝可梦页与跳转后的地图页名称保持一致。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.2%。

- [x] P2 地图视角的encounter列表做下分类,草丛/钓鱼/冲浪,在列表内的展示想象怎么能做好分组或者块展示
  - 结果：地图字典页和右侧详情的 Encounter 改为按草丛、钓鱼、冲浪、碎岩、定点、赠送、蛋等方式分组展示；钓鱼条目保留旧/好/超级钓竿的具体方式。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.2%。

- [x] P2 字典表中的Encounter列表好像有缺失,比如妙蛙种子,我是在游戏中抓到的,但显示Encounter为空
  - 结果：字典表宝可梦 Encounter 现在合并展示 ROM 野生 Encounter 和存档里已捕获宝可梦的实际相遇地点/初始 Lv；没有野生记录但存档中出现过的种族会显示“存档 …”记录，并可跳回对应队伍或盒子位置。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.2%。

- [x] P2 宝可梦修改页里的Encounter,是要展示宝可梦实际相遇的地点和初始等级,而不是宝可梦可以在哪里相遇的列表
  - 结果：解析 `met_location`、初始等级、来源版本和 OT 性别；宝可梦编辑表单底部 Encounter 改为展示这只宝可梦自身的实际相遇地点和初始 Lv，不再跟随种族输入刷新为野生 Encounter 列表。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.1%。

- [x] P1 宝可梦页面悬停显示的文字,仅显示名称就行
  - 结果：队伍格和盒子格的悬停浮层、原生 title 都只展示宝可梦名称，不再附带队伍/盒子位置。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.5%。
- [x] P1 宝可梦编辑页面如果点击到了箱子或者箱子的空位,清空右侧编辑内容
  - 结果：点击队伍/盒子卡片或空位会清空右侧宝可梦编辑表单，并取消上方格子和下方列表行的选中高亮。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.5%。
- [x] P1 宝可梦编辑页面不显示最上方的“盒子1-15合法性通过”
  - 结果：选中队伍或盒子宝可梦时，右侧顶部只显示宝可梦名称和位置，不再展示合法性明细；合法性结果仍保留在列表列中。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.5%。
- [x] P2 Encounter目前显示的地图名不是游戏看到的地图名,搜索下映射表,在UI展示地图中名字
  - 结果：Encounter 地图组/地图号会按 Emerald `map_groups` 顺序映射为 UI 可读地图名，例如 `0-18` 展示为 `103号道路`。
  - 结果：Encounter 数据保留 `location_id` 原始地图编号和 `map_key`，便于后续核对 ROM hack 的差异。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.5%。
- [x] P1 字典表内页面的展示信息更加原子化,需要异化字典表各个子页面的展现形态
  - 结果：字典表按“全部/宝可梦/特性/招式/道具”生成不同列结构；宝可梦展示属性、种族值、特性和成长字段，道具展示口袋、价格、类型和携带效果，招式/特性展示各自描述来源。
  - 结果：右侧字典详情从纯文本改成原子字段块，保留字码、原始字节、描述和存档引用。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.3%。
- [x] P1 添加属性克制表
  - 结果：字典表新增“属性克制”子页，展示第三世代 18 属性攻击/防守矩阵，并提供双属性防守组合倍率汇总。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.3%。
- [x] P2 在字典表页面加上存档位置的超链接,并支持跳转
  - 结果：字典表“存档引用”和右侧详情里的引用改为可点击按钮，可跳到背包、队伍或盒子对应位置并打开右侧编辑表单。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.3%。
- [x] P2 存档已修改内容,能有地方显示改了什么,放在未保存那里,点击展开?
  - 结果：后端状态新增未保存修改列表；背包、队伍和盒子写入会记录修改摘要，保存、重载、关闭会清空。
  - 结果：顶部状态显示“未保存 N”，点击后在右侧展开本轮未保存修改。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.4%。
- [x] P2 在字典表的宝可梦页面添加所有Encounter,需要逆向rom得到信息,逆向的内容记得
  - 结果：逆向并实现当前 ROM 野生 Encounter 表解析，species 字典会展示地图组/地图号、遭遇方式、等级范围、遭遇率和槽位。
  - 记忆：活动 Encounter header table `0xEA2D34`，旧表 `0x552D48`；header `20` bytes，方式指针指向 `rate u32 + wild_list pointer`，wild list 每项 `min_level u8 / max_level u8 / species u16`；地图脚本/object/coord/bg script 中 `0xB6 setwildbattle` 为定点 Encounter 来源，`0x79 givepokemon` 为赠送来源，`0x7A giveegg` 为蛋来源；进化来源不并入 Encounter 显示。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.4%。
- [x] P2 在宝可梦相关的位置展示宝可梦的属性(第一/第二),渲染成与游戏相同的模式,而非文本
  - 结果：后端按当前 ROM base stats 推导 species 属性，队伍/盒子列表和宝可梦编辑表单用彩色属性徽章展示。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.4%。
- [x] P2 添加Encounter后,在宝可梦编辑页面显示相遇位置
  - 结果：宝可梦编辑表单显示当前 species 的 Encounter 面板，并在 species 输入改变时同步刷新属性与 Encounter。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.4%。
- [x] P2 盒子我希望展现成跟模拟器一样,各个盒子以小图+宝可梦实际位置的方式展示,点击盒子激活后展示宝可梦列表
  - 结果：盒子页“全部”视图展示 14 个盒子的 6x5 缩略格；点击盒子后展示该盒 30 个实际位置格，并保留下方宝可梦列表和编辑入口。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.4%。
- [x] P2 bugfix:为什么属性克制里会有未知09
  - 结果：属性克制矩阵只展示第三世代 17 个正式战斗属性，内部 `type id 9` 不再出现在属性克制 UI。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.4%。
- [x] P2 bugfix:字典表特性里显示:扩展特性的描述指针未可靠定位，当前只展示名称。游戏中是能看到的,需要逆向一下ROM找到描述
  - 结果：逆向并接入扩展特性描述指针表，`ability 78..150` 不再显示“描述指针未可靠定位”。
  - 记忆：基础特性描述指针表 `0x31BAD4` 覆盖 `0..77`；扩展特性描述指针表 `0x1BFFE00` 覆盖 `78..150`。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.4%。
- [x] P2 未保存修改加一下跟原结果的查分,并展示出来
  - 结果：未保存修改记录改为结构化数据，背包和宝可梦写入会记录字段级原值/新值差分。
  - 结果：点击顶部“未保存 N”时，右侧面板展示修改摘要和差分表。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.4%。
- [x] P1 去掉盒子页下面原来用来点击的盒子tab,仅通过箱子来切换就行,点击箱子后,不需要把箱子展开,直接弹出列表即可
  - 结果：盒子页移除原来的盒子子 tab；全部盒子视图只展示 14 个箱子卡片，点击箱子后直接进入该盒宝可梦列表。
  - 结果：箱子卡片内的小格只作为预览，不再拦截点击或展开 30 格明细。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.4%。
- [x] P1 字典表页去除全部tab,其他几个tab也锁定在上方,不随滚动条挪动
  - 结果：字典表去除“全部”子 tab，默认进入宝可梦页；字典子 tab 在内容滚动区顶部 sticky 固定。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.4%。
- [x] P1 盒子增加悬停显示名字能力
  - 结果：盒子缩略格为非空宝可梦提供 `data-name` 和原生 title，并用悬停浮层显示宝可梦名与盒内位置。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.4%。
- [x] P1 特性页可以去除描述来源了
  - 结果：特性字典页去除“描述来源”列，右侧详情也不再展示描述来源字段。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.4%。
- [x] P1 字典表中的所有子页可以都把字符码去掉了
  - 结果：字典表搜索、表格列和右侧详情去除可见字符码/原始字节展示，内部 tokens 仅保留给解析和兼容逻辑使用。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.4%。
- [x] P1 道具中去掉????占位
  - 结果：道具名和描述中的纯问号占位不再覆盖内置名称；字典 API 展示为“空”、已有内置名或“道具 ID”，纯问号描述置空。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.5%。
- [x] P1 字典表-宝可梦页面下的属性,没有像修改部分一样显示颜色
  - 结果：字典表宝可梦页的属性列和右侧详情改用与队伍/盒子编辑区一致的彩色属性徽章。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.5%。
- [x] P1 队伍页和盒子页合并到一起,叫宝可梦页,整体是半图半表的格式,半图叫盒子区,半表叫列表区,盒子区展示队伍6只与14个盒子总计15个类似盒子的元素,队伍跨两行,均分6格展示宝可梦图片,当点击某个盒子时,盒子区不动,下方展示列表区
  - 结果：主导航合并为“宝可梦”页；上方盒子区固定展示队伍卡和 14 个盒子卡，队伍卡跨两行并用 6 格展示队伍图片。
  - 结果：点击队伍或任一盒子只切换下方列表区，列表行继续打开原有队伍/盒子宝可梦编辑表单，字典存档引用跳转同步改到新页。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.5%。
- [x] P1 道具页的存档引用点击无响应
  - 结果：字典表道具存档引用支持真实背包引用格式 `口袋 #格位 x数量`，点击后会跳转到背包对应格并打开编辑表单。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.5%。
- [x] P1 宝可梦编辑页的encounter放到最下面
  - 结果：宝可梦编辑表单里的 Encounter 面板移到招式区之后，种族切换时仍会同步刷新 Encounter 内容。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.5%。
- [x] P1 队伍6只改成完全纵向排列
  - 结果：宝可梦页队伍卡的 6 个队伍格改为单列纵向排列，并取消队伍格方形比例以避免高度过大。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.5%。
- [x] P1 宝可梦的盒子区锁定,不随页面滚动,下面的列表区自己单独滚动
  - 结果：宝可梦页改为固定高度上下布局；盒子区固定在上方并限制最大高度，列表区作为独立滚动区域。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.5%。
- [x] P1 去除字典表里的0号宝可梦
  - 结果：字典 API 输出层过滤 `species #0`，字典表和种族输入候选不再展示 0 号宝可梦。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.5%。
- [x] P1 宝可梦页面的属性稍微宽一点,让一排能放下两个
  - 结果：字典表宝可梦页的属性列加宽，双属性徽章在该列内保持同排展示。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.5%。
- [x] P1 宝可梦页面的种族值,嗯不需要每一个都上那么多的框,然后可以在种族值那儿分成6列,每列填数字.成长跟雌雄好像混在一起了,然后分成两列.
  - 结果：字典表宝可梦页的种族值改成轻量 6 列数字展示；原“成长”列拆成“经验曲线”和“性别”两列。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.5%。
- [x] P1 在宝可梦这个图表区点击某一个宝可梦,也可以直接激活右边的编辑栏.
  - 结果：宝可梦页上方图表区的队伍格和盒子预览格都可直接点击，点击后会切到对应列表并打开右侧宝可梦编辑表单。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.5%。
- [x] P1 去除字典表中特性/招式/道具的无实际使用内容(0号,道具+编号的)
  - 结果：字典 API 过滤特性、招式、道具的 0 号占位和“特性/招式/道具 + 编号”形式的无实际名称项。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.5%。
- [x] P1 单击队伍/盒子内的宝可梦时,同步激活所在panel,刷新下方列表,高亮展示上方图与下方表的选中状态,更新右侧修改内容
  - 结果：队伍和盒子宝可梦选择统一同步上方盒子格、下方列表行、当前 panel 和右侧编辑表单。
  - 结果：重复点击当前已选宝可梦不再异步重绘表单，避免覆盖用户正在输入的内容。
  - 验证：`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 通过，总覆盖率 93.5%。
- [x] P0 使用真正的浏览器交互进行单元测试,覆盖显示/修改内容各种场景的测试用例,并在后续的每次任务确保单测通过,即可提交代码
  - 结果：新增后端/API/存档核心测试和 Playwright Chromium 浏览器测试，覆盖真实 `.sav` 加载、背包多轮写入/保存/重载/关闭、队伍和盒子宝可梦修改、超过 100 个宝可梦表单控件交互子用例。
  - 覆盖率：`editor/pokemon_save_core.py` 92.8%，`editor/web_save_editor.py` 94.1%，总覆盖率 93.3%，由 `tests/run_browser_tests.py` 强制校验。
  - 性能：优化覆盖率 trace 后，`PYTHONPYCACHEPREFIX=.pycache python3 tests/run_browser_tests.py` 完整运行约 12 秒。
