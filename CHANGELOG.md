# 🚀 CHANGELOG.md

系统中所有重要升级、重大架构重构、Breaking Changes 以及功能演进均记录在案。

---

## [2.6.45] - 2026-09-19 (双活动对比查询族 —— 登记流水线首个闭环案例)

「两个活动对比」经 agent_unanswered 机制进入视野,按 ADR-0005 登记流水线落地为 `promo_compare` 查询族:两个活动并排对比核销订单数/核销GMV/优惠总额(核销归因口径),需指明两个活动;L3 闭集/提示词支持「A 对比 B」双实体解析(entity_mention + compare_mention 各落一个活动,多命中走 clarify,单命中自动绑定)。eval 补 2 例。同轮修复:promo_compare 编译分支残留 lim 绑定参数导致 SQL 报错(调试脚本实弹抓获)。

验证:gateway analytics 45 passed;vitest/build 绿;实弹「新客50元券 对比 背包品类85折」路径由双活动种核销用例覆盖。

---

## [2.6.44] - 2026-09-19 (data agent 任意问法:LLM 意图层 + 活动效果/对比/客户订单查询族)

grill-me 规划后落地(ADR-0005)。守 08-D1 铁律(LLM 只做语义解析、永不写 SQL),把设计中"L0-L3 四层映射"的 L2/L3 真正接线,并扩容查询族与增长机制。

### ✨ Features

- **L3 LLM 意图兜底**(`analytics/llm_intent.py`):`get_chat_model().with_structured_output` 把任意自然语言解析为闭集结构化意图(metric/方向/limit/时间窗/品类/实体提及),grounding = 指标闭集目录;metric 越闭集/越权/LLM 故障一律响亮失败,绝不静默兜底。`AI_INTENT_L3=off` 一键回滚。
- **两级路由接线**(graph):L0 词表先命中(胶囊零 LLM)→ 未命中 L2 范例回放(query_exemplars ≥0.90,建成未接线 → 接线;L3 成功问句自动沉淀)→ L3 LLM。
- **命名实体解析**(`analytics/dimensions.py`):活动/客户/商品提及 → 确定性 ILIKE 落库命中;唯一命中绑定意图实体槽,多命中 → clarify(entity 类反问,点选原词回问),零命中响亮失败。意图新增 `entity_slot` 命名实体槽。
- **三个新查询族**(首批矩阵成员,核销关联口径):`promo_effect` 活动效果总览(核销订单数/核销GMV/优惠总额);`promo_sku_compare` 活动内商品对比(销量/GMV/订单数,目标款标记);`customer_orders` 客户订单列表卡 —— 前端行级「在订单中查看」写入 PageContext 选中集合并跳订单管理。
- **未命中落库**:0015 迁移 `agent_unanswered`;unsupported 一问一行,作为语义层登记的增长飞轮输入。
- **前端流式**:SSE 增量解析器(`createFrameParser`,撕裂容忍)+ `api.ask` onFrame 逐帧上屏,不再整段等待;胶囊前加「建议问法」。

### 🐛 Fixes

- clarify 反问选项按角色指标闭集过滤(13 号票欠账,文案与实现不一致);metric_head on 路径补 limit/时间窗/品类槽位(与 L0 同源 `_extract_slots`);schema 卡片修正客户表列并补 promotions/核销/会话/售后 4 张分析面表(L3 上下文);L0 反向词补「最少」、order_overview 补勾选/选中同义词。

### 📊 评测

- mapping.json 8 → 38 条(生成器逐条经真实 resolve 校验,按构造即绿);新增 `eval/promptfoo.data.yaml` + echo provider + `test:prompt:data` 脚本(此前 data 用例未挂任何 promptfoo 配置)。

### ✅ 验证 (Verification,如实)

- engine/gateway 契约测试全绿(graph 38、gateway analytics 36 passed);vitest **58 passed**;`tsc && vite build` 绿;biome 0 error。预存失败 2 例(test_colloquial/test_new_metric_families 的 NULL category 插入)经 stash 对照确认为并行会话遗留,与本轮无关。

---

## [2.6.43] - 2026-09-19 (订单域按菜单拆分 + 优惠发券/范围 + 客户详情关联 + TreeTable + 角色全配置化)

grill-me 规划后落地的七项菜单体验收敛;决策结论:售后审批菜单删除并入客服工作台、工作台外壳(头部/指标看板/TabNav)移除、优惠范围只做"全部/指定商品"(券型不展示)、发券入口在优惠活动页、客户详情用抽屉且地址只读、关联订单跳转带勾选、角色去内置化但保留老板防锁死护栏。

### ✨ Features

- **订单域按菜单拆分**:工作台改 `scope` 渲染 —— 订单履约=纯订单列表;客服工作台=在线聊天+待办审核同屏;接口日志=纯流水;「售后审批」菜单删除(迁移 0014 清理存量行),审批里的"进会话"改为路由跳转。删除 StatCards/TabNav/工作台头部/SpusTab/SkusTab(商品库已有独立页),workbench 状态随之瘦身(去掉 activeTab/spus/skus 域)。
- **优惠发券给用户**:`POST /promotions/{id}/grant`(复用商城领券护栏:仅券型/在售/同人同活动一次);券型在售活动行内「发券」→ 客户搜索面板逐个发放,可连续发。
- **优惠适用范围**:满减/折扣建活动可选"全部商品/指定商品(单 SPU)",列表新增范围列;券型不展示范围(引擎对券无视范围,如实不提供)。引擎口径注记:范围优惠按整单金额计算;品类范围引擎未实现,列为后续改造项。
- **客户详情抽屉**:基本信息/累计消费、只读地址簿(商城收货沉淀)、关联优惠券(含已使用)、关联订单列表 + 「在订单中查看」(写入 PageContext 选中集合并跳转订单页)。客户列表接口补充 email/地址簿;新端点 `GET /customers/{id}/coupons`。
- **菜单管理 TreeTable**:目录层级展开/收起(纯函数 `tree-rows` + 单测),类型徽标、权限点展示,叶子删除。
- **角色全配置化**:角色列表不再有"内置"分类,三档种子即预置配置、可重新分配;新建同名角色以 role_menus 存在校验拦截;员工邀请/表格的角色下拉动态取自角色列表。
- **员工管理三维筛选**:关键词(姓名/邮箱)+ 角色 + 状态(纯函数 + 单测)。

### 🐛 Fixes

- **SKU 库存页空列表根因**:开发网关未重启加载 `GET /api/admin/analytics/skus`(返回 404 被前端吞成空)。重启后实测 92 行真实 SKU。

### ✅ 验证 (Verification,如实)

- gateway pytest **126 passed, 3 skipped**(新增发券闭环/客户关联券/403 用例);vitest **53 passed**(15 文件;新增 staff 筛选/tree-rows/scopeLabel 纯函数 + GrantPanel/CustomerDetailDrawer/RedeemPanel 组件用例)。组件测试按用户决议**不 mock 数据**:fetch 仅透传到本地网关,全部断言来自真实后端/真实库(网关未启动时自动跳过);核销成功/幂等等写路径由 gateway 契约测试(密封真实库)覆盖。
- `tsc && vite build` 绿;biome lint 0 error。
- 实弹(开发库,重启网关后):迁移至 0014;`/skus` 92 行;发券 → 重复发被拦 → 客户关联券回读;菜单树已无"售后审批"。验证数据(验证券/发券记录)已按用户确认清理。

---

## [2.6.42] - 2026-09-19 (SKU 库存独立页 —— 与商品列表区分)

此前「商品列表」与「SKU 库存」两个菜单渲染同一个组件(`/skus` 复用 ProductsPage),页面完全一样。

### ✨ Features

- **SKU 库存独立视角页**(`pages/goods/skus`):跨 SPU 的 SKU 库存总表(SKU 编码/名称/所属商品/价格/库存),低库存(<50,与工作台同口径)与关键词(编码/名称/商品)筛选,行内改价/改库存,低库存标红;结构性增删(新 SKU/删除)仍归「商品列表」的展开子表,两页职责分明。
- **网关新端点** `GET /api/admin/analytics/skus`:JOIN merchant_spus 输出 spu_title,JWT 租户闸一致(LIMIT 500)。

### ✅ 验证 (Verification,如实)

- gateway pytest **34 passed, 3 skipped**(新增库存总表契约用例);vitest **37 passed**(新增 filterSkuStock 纯函数 4 例 + SkuStockTable 组件 4 例);`tsc && vite build` 绿;biome lint 0 error。

---

## [2.6.41] - 2026-09-19 (剩余菜单页拆分组件 + 前端单测基建)

### ♻️ Refactoring

- **角色管理**:拆 `PermTree` 勾选树 / `RoleAssignPanel`(挂载即回填勾选态)/ `RoleCreateForm`;勾选树纯逻辑(勾父带子、不可变集合)抽 `lib/perm-tree.ts`。
- **员工/菜单/客户管理**:各拆"创建表单 + 列表表"两个组件(员工共用 `ROLE_LABEL`)。
- **API 收口**:新增 `api.staff` / `api.menuAdmin` / `api.customers`;`api.roles` 统一迁 `fetchJson`(业务 4xx 仍返回 body,页面错误文案不受影响)。
- **lib/sse.ts**:SSE 帧解析独立成模块(坏 JSON 跳过不断流),`api.ask` 复用。

### ✨ 单测(前端从零到一)

- vitest + jsdom + @testing-library 接入,`bun run test`;setup 手动 `afterEach(cleanup)`(globals 关闭时 RTL 不自动清理)。
- **29 用例**:perm-tree 集合运算、sse 帧解析、api 会话凭证/业务 403 不抛错/staffSwitch 换签与切回链路、PermTree・AskInputBar・AskTranscript・EffectCards 组件渲染与交互。

### 🐛 Fixes

- a11y:侧边栏菜单项 span→真 button、FloatingAgent/退出等按钮补 `type`——biome lint 0 error(仅剩原风格 warn 级 noArrayIndexKey)。

### ✅ 验证 (Verification,如实)

- vitest **29 passed**;`tsc && vite build` 绿;e2e 依赖选择器/文案不变。

---

## [2.6.40] - 2026-09-19 (商户后台前端按功能拆分组件 + 渲染优化)

apps/merchant-admin 功能最重的几页按功能域拆成组件,行为与文案不变。

### ♻️ Refactoring

- **订单工作台**(原 index 855 行 → 73 行薄壳):拆出 内嵌顶栏 / 四栏指标看板 / Tab 导航 / 审批 HITL 队列(含行组件、状态徽标、参数列分派)/ 发货弹窗 / 驳回原因弹窗 / SPI Payload 弹窗;行类型独立 `workbench.types.ts`;workbench hook 的计数与六组过滤集全部 `useMemo` 化。
- **商品目录**(217 → 26 行编排):拆出 新增表单 / SPU 表(行内编辑+上下架+删除)/ SKU 子表(自持明细);顺修列表 `<>` 缺 key 的 React 告警;SKU 明细改为展开时才拉取。
- **优惠活动**(207 → 28 行编排):拆出 效果速览卡 / 新建表单 / 核销面板 / 活动表。
- **数据分析**(126 → 52 行编排):拆出 问答流水渲染(气泡/折线卡/表格卡/反问)与底部输入栏;输入框由 `getElementById` 反读改为受控。
- **API 收口**:`lib/api.ts` 新增 `api.products` / `api.promotions` 域客户端(业务 4xx 仍返回 body 供页面展示文案),页面不再手拼 fetch。

### 🐛 Fixes

- **工作台六 tab 原先全部堆叠渲染**(自独立工作台移植的遗留):切 tab 只有审批块受控,订单/客服/SPU/SKU/审计五个 tab 无条件渲染。现在各 tab 组件按 `activeTab` 自行门控,一次只渲染当前功能域(大幅减少常驻 DOM 与轮询渲染面)。

### ✅ 验证 (Verification,如实)

- `tsc && vite build` 通过;biome lint 0 error(5 个 warning 为原实现遗留的 noArrayIndexKey,级别 warn);e2e 依赖的选择器/文案(胶囊、发送、生成报告、活动名称/门槛/优惠、停用/已停用等)全部保持不变。

---

## [2.6.39] - 2026-09-19 (商户后台 RBAC 收口:按钮权限动态化 + 员工 JWT 登录)

商户后台权限从"半套"补成完整模型:按钮权限点(perm_code)不再硬编码于网关,统一由 `role_menus ⨝ menus.perm_code` 动态派生;身份从"信任 x-user-id 头"收口为"解析 Bearer JWT → staff_members",员工各自真实登录,老板可在角色管理页勾选菜单+按钮分配权限,保存即生效。

### ✨ Features

- **员工密码登录(0013 迁移)**:`staff_members` 加 `password_hash`;`/api/auth/login` 员工凭证优先、平台账号(`users`)回落;种子三账号(`test@example.com`/`ops@aurora`/`wh@aurora`)与邀请员工均以种子密码(`E2E_ACCOUNT_PASSWORD` 可覆写,默认 agent-all-dev)可登录。
- **按钮权限动态化**:`rbac.perms_for_role()` 从 role_menus 派生权限点闭集(finance_owner 兜底全量);SPU/SKU 写操作(prod:edit)、报告生成/导出(report:gen/report:csv)、优惠创建/停用/编辑/核销(promo:create/promo:disable/promo:redeem,新增核销按钮节点)全部改为权限点驱动;内置角色种子面修剪为与原硬编码 `_perms()` 等效(迁移清理存量 role_menus 行,升级前后权限不变)。
- **指标权限可自定义**:角色持 `metric:<registry key>` 权限点(菜单管理自行登记,如 metric:gmv_trend)即按点过滤指标;未配置回落内置三档闭集。
- **身份切换换签 token**:`POST /staff/switch` 仅老板可调,服务端为目标员工签发 JWT(旧实现任意 staffId 自报身份,已拆除);前端保存原始老板凭证,切换/切回均以老板 token 发起。
- **角色管理页完整化**:菜单+按钮三级勾选树(勾父带子、按钮带 permCode 徽标),新建角色与再分配共用;新增 `GET /roles/{role}/menus` 回填勾选态;新建角色拒绝覆盖内置角色名;`/menus` 响应附带 `perms` 闭集。

### 🔒 Security

- `/api/admin/analytics/*` 不再信任 `x-user-id` 头:无/坏 token 401,非商户员工或已停用 403(旧版未识别员工默认回落 finance_owner 的 fail-open 已删除);`report:csv` 导出端点此前无校验,现由权限点驱动;停用员工禁止登录。

### ✅ 验证 (Verification,如实)

- gateway pytest **165 passed, 2 skipped**(新增 JWT 身份/权限点授予回收/metric 点/停用员工禁登等 9 个用例);engine graph 套件 32 passed(越权用例改为桩掉动态派生层保持无 DB);ruff 干净;merchant-admin `tsc && vite build` 通过。

---

## [2.6.38] - 2026-09-15 (购物车图片对齐:车行 imageUrl 全链透传)

用户实报:购物车商品图片不对/没对应上——根因是**车行从不存图片**:`add_to_cart` 落库行只有 skuId/quantity/title/price/spec,没有 imageUrl;前端购物车卡渲染 `i.get("imageUrl")` 恒空,只能落占位/错图。

### 🐛 Fixes

- **imageUrl 全链透传**:①guide 候选(candidateProducts)本就带 catalog 的 imageUrl ✓;②购物车技能两个加购调用点(单加/全量)透传 `imageUrl`;③`add_to_cart` 车行存储补 `imageUrl` 键;④按名直配 `find_shelf_sku_by_description` 返回补 `main_image`。
- 实弹:入车后 Redis 车行每条带各自正确的图(背包=登山包图、渔夫帽=帽图),前端购物车卡渲染 `i.get("imageUrl")` 不再落空。

### ✅ 验证 (Verification,如实)

- engine pytest **656 passed**、gateway 134 过、ruff 干净、promptfoo 双套件 56/0 + 8/0 与基线全对齐;实弹 Redis 车行对账:每条 imageUrl 与商品一一对应。

---

## [2.6.37] - 2026-09-15 (确认链恢复 + 删除地址能力 + 场景别名补齐)

按顺序补齐挂账四项中的三项(②对比 SOP 已于 2.6.31/2.6.33 落地上下文对比分支,本轮不重复)。

### ✨ Features

- **确认链参数继承(S8/S3/S7 同族根治)**:triage 新增肯定确认恢复闸——上一轮留下 pendingAction(tool+args)且本轮是「是的/确认/对」时,确定性恢复执行该动作,LLM 确认轮不再丢上下文参数;saveUserAddress 成功时 executor 登记 pendingAction 随 task_plan 落 TaskMemory。
- **删除地址能力(deleteUserAddress)**:按收件人/full_address 子串定位顾客账本条目并移除,找不到/多命中如实说明;检出词表补前置/后置删除形;工具注册+白名单+快路径。
- **场景词元别名**:爬山→(高山,徒步)、登山→(高山)——「我经常爬山买哪种背包」命中真实徒步装备。

### 🐛 Fixes

- **ORDER_MODIFY_ADDRESS 负向豁免**:「改成默认/设为默认」是地址簿操作不是改单——曾截胡反问订单编号(S8 实弹)。
- **ecommerce_sop_guides.md 编造政策修正**:「已发货自动联系快递员改派、转寄费自理」无执行面支撑,改如实表述(幻觉话术源头清除)。

### ✅ 验证 (Verification,如实)

- engine pytest **656 passed**、gateway 132 过、ruff 干净;promptfoo 双套件对齐(unified 56/0 多轮稳定、planner 断言层零失败;planner 偶发 1-2 条 LLM 读超时/DNS 抖动系上游传输不稳,非断言回归,重跑即清)。
- 实弹:「改成默认」不再被截胡反问订单号;门牌变化的新地址真实执行保存(数字指纹判据);删除地址检出后 LLM 诚实列地址反问删哪条(多轮确认正确)。

---

## [2.6.36] - 2026-09-15 (设默认地址能力落地 + 多轮确认链参数丢失如实记录)

2.6.34 诊断轮 S8「刚才那个地址改成默认」能力补齐。

### ✨ Features

- **setDefaultAddress 工具 + 服务层**:按收件人/地址 id 定位顾客账本条目(子串双向匹配兼容 LLM 转述形态),置 is_default 清其它默认;找不到/歧义列出候选举名。工具注册 + executor 白名单 + 快路径直配 + planner address_manage set_default 段。
- **ORDER_MODIFY_ADDRESS 规则负向豁免**:「改成默认/设为默认」是地址簿操作不是改单——曾截胡反问订单编号。

### ⚠️ 已知残留(如实)

- **多轮确认链参数丢失(S3/S7 同族)**:「把王五的地址设为默认」→ 助手列出地址请确认 →「确认」后 LLM 调 save_user_address 空参触发 M7 防线诚实失败。服务层能力本体已验证可用(直接调用成功置默认);断点在确认轮 LLM 丢上下文参数——跨轮参数继承是架构级议题,与 S3/S7 同族,留待专项。

### ✅ 验证 (Verification,如实)

- engine pytest **654 passed**、gateway 132 过、ruff 干净、promptfoo 双套件 56/0 + 8/0 与基线全对齐。
- 实弹:服务层直接调用设默认成功(王五→成都地址 is_default=true);「改成默认」不再被截胡反问订单号;「把王五的地址设为默认」列出地址请确认(诚实多轮流)。

---

## [2.6.35] - 2026-09-15 (第五轮修复:跨品类错单/守卫误报/查单漏/上下文价位重检)

2.6.34 诊断轮 6 症中的 4 症收口(S3/S7 追问链与 S8 设默认地址留待后续)。

### 🐛 Fixes

- **S6 跨品类错单(P0)**:「推荐帐篷」(走追问)→「就要第一个,直接下单」——序数「第一个」指代悬空时,购物车技能与 checkoutCart 快路径双双拿**购物车遗留品**(老爹鞋+渔夫帽)开真实订单。双闸修复:cart 技能结算分支遇序数 × 无本轮候选 → 诚实反问目标商品;executor 快路径 `_intent_target_missing` 谓词拒配 checkoutCart。
- **S1 守卫误报**:技能快轨 bypass 计划无步骤级回执,加购成功后仍被追加「加购未真实发生」——守卫背书扩认 `skill_fast_track_skill_cart_manage` bypass 描述。
- **S2 查单快轨漏**:「查一下我最近的订单」被 ORDER_QUERY 规则截胡进缺槽反问——`_RECENT_ORDERS_RE`(最近/最新+订单)列表形优先列单(与「查询我最近的订单」同待遇),实测直列 32 笔真实订单。
- **S5 上下文价位丢失**:「最贵的背包」→「有没有中间价位的」诚实空——上下文重检分支从对比语义泛化到价位带(中间价位/中等价位):用上轮品类词重检,去首尾极值只留中位段。
- **兼容修复(另一会话按名直配回归)**:按名直配把「询评价好的短袖，并把第一个加入购物车」的检索半残词(「询评价好的短袖，并 个」)当商品名查货架,吃掉幻影守卫的诚实反问——检索诉求词(询/推荐/评价…)在场时残词不进按名直配。

### ✅ 验证 (Verification,如实)

- engine pytest **654 passed**(+3:指代悬空谓词矩阵/守卫背书/价位重检;兼容另一会话的按名直配套件),gateway 132 过,ruff 干净,promptfoo 双套件 56/0 + 8/0 与基线全对齐。
- 实弹四场景:S6 拒结遗留车(购物车原样保留,零新订单);S1 序数加购成功零误报;S2 直列 32 笔真实订单;S5 背包中间价位直出(¥259/¥499)。

---

## [2.6.34] - 2026-09-15 (第五轮多轮指代链矩阵:8 场景实测,发现并如实记录 6 症)

用户要求多测「多轮指代链」——序数跨轮/槽位继承/否定回指/比较基准切换 8 场景连续对话实测(库级对账)。**本轮为诊断轮:6 症全部如实记录,尚未修复,待用户裁决修复优先级。**

### 🔍 发现的问题(按危害排序)

1. **S6 跨品类错单(最危险)**:会话里先说「推荐帐篷」(引擎走了追问),后说「就要第一个,直接下单」——下单的是**购物车遗留的老爹鞋+渔夫帽**(库对账 AURORA-ORD-2026-8706,¥1028),与「帐篷」完全无关。「第一个」的指代对象(本轮推荐)不存在时,不应拿购物车遗留品结算。
2. **S1 序数错位+守卫误报**:「推荐三款背包」→「把第二个加入购物车」——加入的是候选第 2 款 ✓ 但追加的守卫诚实说明(「加购未真实发生」)在真实加购成功时仍出现(误报);且金额 ¥1028 混入了历史遗留品。
3. **S2 查单快轨漏**:「查一下我最近的订单」被要求提供订单号——「我最近的订单」应触发 listUserOrders 列单流。
4. **S3/S7 超模糊追问打断**:「推荐跑鞋/短袖」触发追问(男款女款),二轮「大一号的有吗/买两件」脱离推荐上下文回答——追问状态未与指代链衔接。
5. **S5 上下文品类丢失**:「最贵的背包」→「有没有中间价位的」——二轮没用上下文品类词(背包)重检,诚实空。
6. **S8 地址能力缺口**:「刚才那个地址改成默认」被路由到改单地址反问——设默认地址能力未建。

### ✅ 验证 (Verification,如实)

- 全部场景输出与库级对账已存档:`.scratch/address-order-bug/c5_matrix.py` / `c5_results.json`;engine 647/gateway 132/promptfoo 双套件全对齐(本轮零代码改动,纯诊断)。

---

## [2.6.33] - 2026-09-14 (上下文指代式对比:「最贵的和最便宜的对比」不再诚实空)

用户实报:「最贵的 背包」推荐后,追问「最贵的和最便宜的对比，有什么不同」得到「暂未找到现货商品」——指代式对比句无品类词(极值词剥除+指代上一轮),词元只剩「对比/不同」,检索必空。

### ✨ Features

- **导购技能上下文对比分支**:检索空 × 命中对比语义词(对比|不同|差别|区别|比一比)× guideContext 有 lastSearchQuery 时,用上一轮检索词重提品类词,经 search_products 完整链重新检索,取最便宜与最贵两档对比展示(名称/价格/库存/价差)。

### ✅ 验证 (Verification,如实)

- engine pytest **647 passed**(+1:指代式对比必须用上下文品类词重检且输出含两档价格)、gateway 132 过、ruff 干净、promptfoo 双套件 56/0 + 8/0 与基线全对齐。
- 实弹(同 thread 两轮):「最贵的 背包」→ 真背包推荐;「最贵的和最便宜的对比」→ 背包品类最便宜 ¥129(渔夫帽)vs 最贵 ¥829(徒步背包)+ 价差 ¥700,1.5s。

---

## [2.6.32] - 2026-09-14 (第四轮负向/边界/泄漏矩阵:三症收口)

用户要求「开动脑筋多思考不同场景」——第四轮 12 探针覆盖否定意向/矛盾指令/能力缺口/越权/边界,新抓三症。

### 🐛 Fixes

- **反幻觉守卫误伤查单语境(N3 实报)**:「查一下订单 AURORA-ORD-2026-9999」的诚实查无回复被守卫改写,内部标记「（无效订单号，已由系统核对移除）」直接泄漏给用户——守卫加语境门槛:只拦「下单/结算成功」宣称,查单叙事提及单号一律放行。
- **工具 JSON 泄漏给用户(N12 实报)**:「退货转换货」回复把工具回执 JSON 原样吐出(`执行详情：[{"toolExecuted": "listUserOrders"...}]`)——收口处剥离 raw dump。
- **否定购买意向被强行推荐(N2 实报)**:「我不想买了，别给我推荐任何东西」仍进导购快轨搜索+品类盘点——技能否定守卫(不想买|别推荐|停止推荐)让位,不再强行推荐。

### ✅ 验证 (Verification,如实)

- engine pytest **644 passed**(+3)、gateway 132 过、ruff 干净;promptfoo 双套件对齐(unified 56/0、planner 单跑 8/8 零错误;planner 偶发单条 LLM 读超时为传输抖动,断言层零失败)。
- 其余探针行为正确:清空后结算矛盾(诚实拒结算)、不存在订单(诚实查无)、越权退单(归属校验拦截)、纯表情/超长无意义(礼貌引导)、上下文切换(背包→帐篷正确切品)。已知残留:删除地址能力未建(转人工接管,能力缺口如实呈现)。

---

## [2.6.31] - 2026-09-14 (价格极值/对比/场景化推荐:14 探针专项矩阵,转圈与检索稀释收口)

用户要求对「最便宜的X / 商品对比 / 我经常爬山买哪种背包」类意图多轮实测——T3 矩阵 14 探针:全部漏出导购快轨走 LLM 深规划,**25~236 秒(T8 超 300s 客户端超时,即「一直转圈」)**,且「最便宜的背包」检索被「便宜」词元稀释(头巾/水壶按价格升序顶了真背包)。

### ✨ Features

- **导购词表扩容**(技能 _FALLBACK_RE + slot 规则双侧):最便宜|便宜点|最贵|性价比|哪个好|怎么选|有什么区别|买哪种|背什么|用哪种|什么包|该用什么|需要准备什么——价格极值/对比/场景化问法全部进导购快轨(毫秒级 SOP,零 LLM)。
- **价格极值排序**:search_products 支持 sort=price_desc(「最贵的X」首条即最贵);「最便宜」默认价格升序天然满足。
- **场景词元别名**:爬山→(高山,徒步)、登山→(高山)——「我经常爬山买哪种背包」命中真实徒步装备。

### 🐛 Fixes

- **词元稀释**:「最便宜的背包」的「便宜」曾混入词元(四列 OR 把头巾/水壶的 description 弱命中拉进来按价格升序顶了真背包)——价格极值词在词元清洗中剥除,排序语义交给 sort。
- **疑问词/口语前缀污染**:「最贵的冲锋衣是哪款」曾整块成词元「冲锋衣是哪款」ILIKE 必空;「我经常爬山」的「我经常」前缀同理——疑问词(是哪款/哪种/什么/怎么样/好吗)与口语前缀(我/经常/买/问/看…)两道清洗,循环剥前缀。

### ✅ 验证 (Verification,如实)

- engine pytest **641 passed**(+3:13 句快轨词表覆盖/价格极值词元剥除/price_desc 排序),gateway 127 过,ruff 干净,promptfoo 双套件 56/0 + 8/0 与基线全对齐。
- 实弹 T3 矩阵复跑:**14/14 全部导购快轨,0.4~2.7s**(原 25~236s/超时);抽查质量:「最便宜的背包」首位即真背包 ¥829、「最贵的冲锋衣」直出旗舰款、「日常通勤背什么包」→ 城市通勤双肩包、「爬山买哪种背包」→ 徒步鞋+高山背包。

---

## [2.6.30] - 2026-09-14 (地址簿单账本统一:聊天与商城前端同一存储)

用户实报:聊天「新增地址」回复保存成功,但前端「我的地址」刷新看不到——**双库分裂**根因:聊天把地址写进引擎库 `user_addresses`,商城前端读的是商户库 `merchant_customers.addresses`,两个存储永不相交。

### ✨ Features

- **地址簿单账本统一**:聊天的地址簿读写全部切换到商户侧 `merchant_customers.addresses`(与商城前端「我的地址」/结算默认地址同一存储)——聊天新增的地址在前端立即可见,前端添加的地址聊天也能列出;首条自动设默认、显式默认清除其它默认(与商城前端同语义);手机号存储脱敏。引擎旧表 `user_addresses` 退役(遗留数据已一次性迁入商户账本,按 full_address 去重)。
- 顺带修复:checkout 默认地址查询同步切商户账本;商户账本 upsert 补全 NOT NULL 列(name/phone)。

### ✅ 验证 (Verification,如实)

- engine pytest **638 passed**(地址簿用例改钉商户账本缝,零回归)、gateway 132 过、ruff 干净、promptfoo 双套件 56/0 + 8/0 与基线全对齐。
- 实弹全链路:聊天「新增地址…7777室」→ 保存成功 → 「地址列表」8 条 → **商城前端地址接口(`/api/store/addresses`)立即可见 7777**;「结算下单」空车诚实告知。迁移后遗留数据(张伟/李四/王五/测试用户)在账本中保留。

---

## [2.6.29] - 2026-09-14 (语义重复拦截数字指纹:槽位数字不同的相似句是新请求)

用户实报:新增地址(1211室,与上次 1402室 仅差门牌)收到上次的确认重放,新地址未执行保存——语义重复拦截按向量相似度 ≥0.98 判重,两句几乎逐字相同必然过线,旧确认重放顶掉了新保存。

### 🐛 Fixes

- **重复拦截数字指纹判据**:语义相似(≥0.98)还必须数字串序列一致才算重复——门牌/单号/数量等槽位数字是动作身份的一部分,数字不同的「相似句」是新请求必须真实执行(`_digit_fingerprint` 纯函数)。逐字重复仍正确重放;真单号查询等数字相同场景行为不变。

### ✅ 验证 (Verification,如实)

- engine pytest **638 passed**(+2:数字不同指纹不同/无数字同指纹)、gateway 132 过、ruff 干净。
- 实弹三态:门牌 1402→9999 新保存真实执行(库行核验)+ 不重放;逐字重复仍正确重放;数字相同(退货政策类)行为不变。

---

## [2.6.28] - 2026-09-14 (「我的地址列表」词形补齐:新增后列表直答)

用户实报:聊天新增地址成功后,「我的地址列表」查不到——检出词表缺「我的+地址(列表)」省略形,该句落 general_query 零规划直答(且历史无地址素材时编「地址列表为空」)。

### 🐛 Fixes

- `_ADDRESS_BOOK_LIST_RE` 列表形两支扩展:动词形补「地址列表|列一下」;我的形改 `我的(?:收货)?地址(?:簿|列表)?(?:有哪些|是什么)?$`(「我的地址列表/我的地址列表有哪些/我的地址」全命中)。负例不回归(「查一下订单9081的地址」仍不命中)。
- 实弹闭环:同 aurora 线程「新增地址 赵六…」→「我的地址列表」立即列出 8 条含新建(手机号脱敏);promptfoo 双套件 56/0 + 8/0 与基线全对齐(首跑 planner 2 error 为 LLM 传输抖动,重跑干净);engine pytest 636 passed。

---

## [2.6.27] - 2026-09-13 (「退货策略」咨询直答:裸话题词表一字之差)

用户实报:「退货策略」被退款缺槽反问索要订单号——而「退货政策」(一字之差)此前验收是政策直答。

### 🐛 Fixes

- **咨询闸裸话题词表补「策略」**:`_CONSULT_BARE_TOPIC_RE` 有「政策」无「策略」——无问号短句走裸话题分支时「退货策略/退款策略」不满足咨询判定,落进 ORDER_RETURN 规则的缺槽反问;补「策略|规则|手续」并回归四句同义形。
- **ecommerce 租户补退换货政策知识段**:词表修后 RAG 命中仍空——退换货政策内容只写在 aurora 文档,ecommerce 文档(发票/改地址 SOP)没有该段,直答无素材只能泛答;补「退换货与退款政策」段(7 天无理由/质量问题 15 天换新/48 小时原路退回/特殊商品例外),自愈播种按内容哈希自动重灌(appended 3 chunks)。

### ✅ 验证 (Verification,如实)

- engine pytest **635 passed**(+1 裸话题回归:五句同义形含负例不回归)、gateway 132 过、promptfoo 双套件 56/0 + 8/0 与基线全对齐。
- 实弹:「退货策略」「退货策略是什么」均 RAG 直答完整政策四条(无理由退换/质量换新/特殊商品例外/退款时效),零订单号反问。

---

## [2.6.26] - 2026-09-13 (地址簿两症:租户过滤误伤 + 裸「地址列表」落咨询)

用户实报「地址列表」答「暂无保存的收货地址」,而库中 6 条真实地址全归该顾客。

### 🐛 Fixes

- **地址簿是顾客自有数据,查询严禁按租户过滤**:`get_user_addresses` 曾按 business_id 过滤——同一顾客在极光(aurora)租户线程查询时,chat 测试探针以 ecommerce 租户写入的 6 条真实地址全部查无。查询改按 user_id(写入侧 business_id 保留作归属归因);与 checkout 默认地址查询(本就不过滤租户)口径统一。
- **裸「地址列表」落咨询 RAG**:检出词表只认「查看/看看/查一下×收货地址/地址簿」——裸「地址列表/收货地址列表/地址簿列表」整句锚定补齐,直达 getUserAddresses 真数据直答。
- **知识库编造政策修正**:`ecommerce_sop_guides.md`「已发货系统会自动联系快递员改派、转寄费自理」系无执行面支撑的编造政策(多次幻觉回复的话术源头)——改为如实表述(已发货无法拦截修改,联系人工协调,以物流商实际答复为准)。

### ✅ 验证 (Verification,如实)

- engine pytest **623 passed**(+2:跨租户可见/裸词检出)、gateway 132 过、promptfoo 双套件 56/0 + 8/0 与基线全对齐。
- 实弹双场景:aurora 租户线程与新 thread 的「地址列表」均真数据直答 6 条(手机号脱敏);改派政策编造话术的知识源头清除。

---

## [2.6.25] - 2026-09-13 (「查推荐→加购→结算」三段确定性编排:路由缺口根治)

2.6.24 硬闸兜底的复合流路由缺口根治(用户追问「还是上次流程,为什么这样」):「查询卖的好的短袖，并把第一个加入购物车，地址是X，然后结算」现在真实走完全程。

### ✨ Features

- **导购×购物车×结算三段确定性快轨(planner)**:guide×cart 双意图 → 子任务【ShoppingGuideSkill(检索写候选,数量语义生效)→ CartSkill(序数入车)】+ 句含结算/下单词时追加第三段 checkoutCart(**句中地址嵌入步骤描述**,executor 快路径提取为显式 shippingAddress)。深规划自由发挥曾产出无执行的幻觉叙事——三段零 LLM 编排根治。
- **指标轨让位**:「卖的好的」撞指标词族(卖得好)时指标轨曾抢跑吞掉 cart 半——cart 意图在场时让位三段轨。
- **串行护栏扩**:当前步是技能时后续步骤(含 checkoutCart 工具读车)一律不并行——cart 写车与 checkout 读车也曾被并发。

### ✅ 验证 (Verification,如实)

- engine pytest **615 passed**(+1:三段编排形状+地址嵌入断言)、gateway 127 过、ruff 干净、promptfoo 双套件 56/0 + 8/0 与基线全对齐。
- 实弹(同 thread):一句话 → 热销短袖真数据推荐(320g T恤 销量 8 件)→ 第 1 件自动入车 → 句中北京地址真实结算 → **订单 AURORA-ORD-2026-5097 落库**(¥269,T恤 M 码,库级对账)→ 购物车清空 → 回复报可查的真单号(反幻觉硬闸核验通过放行)。硬闸与三段编排构成「确定执行+失败必拦」闭环。

---

## [2.6.24] - 2026-09-13 (订单宣称反幻觉硬闸:历史幻觉单号自增殖链物理切断)

用户实报:复合流回复宣称订单号 AURORA-ORD-2026-2477,订单列表查无——库级核验:该单不存在、近 8 小时零真实订单;同一 thread 里 09:54 首次幻觉轮报过同一个 2477。**根因是幻觉自增殖**:复合流被判单导购终局(「加入购物车」负向词杀导购规则),加购/结算半无真实执行,下游 LLM 叙事圆场宣称成功;幻觉回复进入对话历史,后续轮 LLM 从历史把假单号抄回来续编。

### 🐛 Fixes

- **订单宣称反幻觉硬闸(run_agent 收口,确定性)**:回复宣称的订单号必须经库核验(`merchant_orders` 真实存在)或来自本轮 checkoutCart/cart 技能成功回执;无凭据宣称(含不报单号的「成功完成结算下单」叙事与「已自动将 X 加入购物车」加购宣称)剥离并追加诚实说明——**幻觉不进对话历史,自增殖链物理切断**;库不可达时放行(宁可漏拦不误杀)。
- 正则与凭据面修复(首轮实弹误杀暴露):单号正则 `AURORA-ORD-\d+` 只吃到「2026」补 `(?:-\d+)?`;cart 技能结算分支(Execute CartSkill)的回执与 checkoutCart 工具同作订单凭据;叙事变体(订单结算成功/结算成功/下单成功)进剥离词表。

### ✅ 验证 (Verification,如实)

- engine pytest **614 passed**(+5:无宣称透传/真单背书透传/幻觉单号剥离/无单号叙事拦截/真实回执单号认可)、gateway 127 过、ruff 干净、promptfoo 双套件 56/0 + 8/0 与基线全对齐。
- 实弹同 thread 重放:幻觉单号 2477 被剥离+诚实说明在场;真单 AURORA-ORD-2026-8039(库中真实存在)被守卫正确放行——守卫可区分幻觉与真单。
- 已知残留如实记录:①宣称句式为词表匹配,LLM 叙事变体可能绕过措辞剥离(单号核验不受影响,假单号必然剥离);②复合流被判单导购的路由缺口仍在(本轮靠硬闸兜底,导购+加购+结算三段确定性编排列后续)。

---

## [2.6.23] - 2026-09-13 (「推荐X，都要了」一句话接力:导购→全量加购跨技能编排落地)

2.6.22 如实记录的残留项收口(用户「要做」):一句话完成「检索→全量加购」自动接力。修复链五层,每层都是实弹抓出:

### ✨ Features

- **推荐×全量加购确定性快轨(planner)**:guide×cart 双意图 + 全量词(都要|全要|一起买)→ 确定性双子任务【先导购(写候选,数量语义生效)后购物车全量入车】,零 LLM。
- **guide 规则负向豁免**:「推荐X，都要了，一起加入购物车」——negative(加入购物车)曾把导购半整个否掉;句首整句前瞻豁免全量形(单件序数加购仍正确否导购)。
- **executor 显式技能名优先**:复合计划子任务描述嵌入对方关键词(「Execute ShoppingGuideSkill … 加入购物车」),关键词匹配曾互相劫持(guide 子任务跑成加购反问)——描述点名技能 id 时直配。
- **执行器技能依赖护栏(串行化)**:并行调度检测曾把 guide→cart 有状态依赖的 SOP 链 gather 并发(cart 在 guide 写候选前读空)——技能型步骤之间一律串行。
- **检索标题命中优先**:「背包」词元经四列 OR 把渔夫帽的 description 弱命中拉进来,价格升序把 ¥829 真背包挤出 LIMIT——title 强命中排 description 弱命中前。
- **数量前缀块内定位**:「推荐两款登山包」块首是「推荐」,^ 锚定剥不掉致词元全死落语义召回(渔夫帽顶了登山包)——改块内最小贪婪定位。

### ✅ 验证 (Verification,如实)

- TDD:engine pytest **609 passed**(+3,一句话接力三针:负向豁免/planner 双子任务编排/executor 技能名互不劫持)、gateway 127 过、ruff 双服务干净、promptfoo 双套件 56/0 + 8/0 与基线全对齐(两轮,首跑 1 error 系 LLM 评委 fetch failed 传输抖动)。
- 实弹:「推荐两款登山包，都要了，一起加入购物车」→ 推荐第一位即真背包(高山徒步轻量化背包)+ 自动全量入车 2 款 + Redis 购物车对账两行全对。诊断过程提示:实弹验证前务必确认网关已重启加载最新代码(两次误判均因进程持旧码)。

---

## [2.6.22] - 2026-09-13 (评价数据面 + 口语组合鲁棒性:两轮实弹矩阵收口)

用户实报复合评价流四症 + 二轮 12 探针口语矩阵的失败面,一个版本收口。

### ✨ Features

- **真实评价数据面**:`merchant_product_reviews` 表(挂商户 SPU,与聊天/商城同一商品身份)+ seed 确定性生成 135 条品类口碑(品类模板 × crc32 取模,4~5 条/SPU,星级 3-5 分层;评价为演示数据与商品同边界,严禁编造具体性能参数);`query_product_reviews` 重写走商户真表——旧实现查 engine 本地 product_reviews(products 域,0 行),评价诉求全链无数据。
- **评价检索词元化 + 滑窗子词**:「三合一冲锋衣」子串不在「极光三合一全天候户外硬壳冲锋衣」中,整词死匹配曾查空——词元化,整词空再 3/2 字滑窗兜底(无分词器的确定性方案)。
- **加购幻影守卫**:历史回溯候选在句中带检索/推荐诉求(推荐|询|看看|评价|热销…)时禁用——「询评价好的短袖，并把第一个加入购物车」曾把上一轮的慢跑裤当「第一个」入车,现在诚实反问。
- **checkoutCart 地址保真**:顾客句中给的地址(地址是…/寄到…)属于新订单——深规划步骤描述携带地址,executor 快路径提取为显式 shippingAddress,严禁静默回落地址簿默认;planner 规则 8 补地址保真条款。
- **催单处置条款(rule 7.5)**:「帮我催催/急用」是查单+话术,严禁仅因顾客催促就创建人工接管(M2 实弹把急用顾客直接推进接管队列)。

### 🐛 Fixes

- **saveUserAddress 缺参 KeyError 炸图**(P0,M7 实弹):缺 province 等必填字段直接下标炸图整轮熔断成「上游模型波动」——补必填字段防线,缺什么如实列出。
- **「加个新地址」检出缺口**:「加/增加」不在创建形动词表,漏检致深规划缺参炸图——补齐。
- **「登山包」词元盲**:子串不在「高山徒步轻量化背包」,词素别名补(登山包→背包/包,腰包/胸包→包)。
- **「两款/三条/两只」量词盲**:guide 数量语义只认「个」——量词族 [个件款条双只]。
- **「都要了/全要/一起买」不入 cart 意图**:slot 规则 pattern 补齐(推荐+全量加购复合流可拆)。

### ✅ 验证 (Verification,如实)

- TDD:engine pytest **606 passed**(+13,两套件:test_review_flow_integrity 6 + test_colloquial_robustness 7)、gateway 126 过、ruff 干净、promptfoo 双套件 56/0 + 8/0 与基线全对齐。修套件间污染:新测试套件曾把共享容器的 merchant_spus 建成缺列窄形状,传染后续套件 43 挂——形状取并集修复(教训:共享容器建表必须防御式全列)。
- 实弹复验:催单 → 真实查单列未发货订单零接管;「加个新地址…然后看看购物车…下单」→ 地址真建+空车诚实告知零炸图;「三合一冲锋衣评价」→ 5.0 分真评价直答;原句复合评价流 → 真实短袖商品+诚实确认+地址记住,零幻影零编造。已知残留(如实记录):「推荐X，都要了」一句话流的检索→全量加购自动接力未达理想(guide 快轨单技能,多技能单轮编排属二期跨域桥接面),当前诚实引导确认。

---

## [2.6.21] - 2026-09-13 (商品知识 RAG 入库:「XX 特点」从「没找到」到真规格直答)

用户实报:「极光 420g重磅毛圈棉抽绳束脚慢 特点」得到「政策资料中没找到相关信息」——RAG 知识库只有店铺政策没有商品信息,商品知识问句全落空。

### ✨ Features

- **静态品类养护知识**(`docs/knowledge/ecommerce_product_knowledge.md`,businessId: ecommerce):六大段——棉质/针织面料特性与洗护、功能性外套(三合一/羽绒/软壳)洗护收纳、鞋靴养护、背包配件养护、露营装备使用存放、选购尺码建议 + 在售主力款尺码速查表——走既有 Markdown 摄取链,零代码。
- **动态商品知识同步器**(`rag/product_knowledge.py`):商户真货架派生每 SPU 一块切片(卖点/核心规格/在售规格与价格/价格区间/库存状态),**内容全部来自 merchant_spus/skus 真实字段,严禁为虚构商品编造参数**(real-data-only/01);source_url=product_catalog_sync.md 整组替换幂等,gateway 启动 lifespan 自动同步(商户改标题/价格重启生效,30 SPU 秒级),商户库不可达诚实跳过。items.spu_id 落 spu_code 契约兼容(历史 UUID/编码两形态 id::text OR spu_code 双匹配)。
- **咨询闸商品知识信号**:「特点/参数/规格/材质/面料/卖点/功能/用途/配置」进 _CONSULT_TOPIC_RE + 知识强信号独立通道(不受 12 字裸话题长度限制)——「极光 420g…慢跑裤 特点」14 字无问号此前进不了咨询直答。

### 🐛 Fixes(顺带挖出的存量 bug)

- **RagDocumentRow(metadata=…) 列从未写入**:关键字传的是 SQLAlchemy Base 类属性名(metadata),真实映射属性是 metadata_ —— 实例 dict 遮蔽类属性不报错,列恒 NULL,search 的 category 过滤/docTitle/headerPath 进 BM25 全部失效;两处播种点(product_knowledge/contextual_rag)修为 metadata_。
- **知识自愈播种升级**:①source 级补齐——原先只在「表全空」时播种,新增知识文件对已播种库永远不可见;②文件内容哈希比对(string_agg MD5,排序无关聚合)——文件修订整组自动重灌,免手动清库。

### ✅ 验证 (Verification,如实)

- TDD:engine pytest **593 passed**(+10:切片真规格/裸 SPU 不编造/幂等/标题变更反映 headerPath/商户不可达诚实跳过/source 补齐/内容修订重灌/咨询闸信号与负例),gateway 121 过、ruff 干净、promptfoo 双套件 56/0 + 8/0 与基线全对齐。
- 实弹:原句 → 逐条真规格直答(420g 重磅毛圈棉混纺/宽松锥形 Easy Fit/高弹罗纹收口抽绳/侧插袋后防盗拉链袋);「三合一冲锋衣怎么洗」→ 完整洗护指南(严禁机洗/30℃ 手洗/压胶条忌熨烫/内外胆分洗);「Vibram老爹鞋尺码怎么选」→ 40-43 码对应脚长速查(文件变更自动重灌验证:appended 7 chunks)。

---

## [2.6.20] - 2026-09-13 (遗留二期:真·聊天下单 + 订单→购物车桥接 + 指标复合确定性编排)

2.6.18/2.6.19 收尾明示的二期三项一个版本收口(用户「遗留二期做」,to-spec → implement)。spec: `.scratch/phase2-bridging-checkout/spec.md`(gitignored)。

### ✨ Features

- **真·聊天下单(checkoutCart)**:MallDomainService.checkout_user_cart —— 购物车逐行解析商户真 SKU(skuId=spu_code 按 SPU 当前 ON_SALE 最低价在售 SKU 结算,与展示价=MIN(price) 同语义,规格如实展示;sku_code 直配),条件 UPDATE(stock>=qty)原子扣减防超卖,**任一行失败整单不落**(all-or-nothing 与商城页同口径),cost_at_purchase 快照落明细,PAID 真单与商城页同一账本(既有发货/退款/改址 HITL 链路直接可消费);地址:显式提供(收件人/电话缺项取地址簿真值)> 地址簿 is_default > 诚实追问(needsAddress,严禁假地址兜底);顾客自有资金下单与商城页同权免审(spec 明示豁免,执行面确定性快路径+库级对账钉死)。items.spu_id 落 spu_code(排行 join 的事实契约)。
- **订单→购物车桥接(add_order_item_to_cart)**:「把我订单里的那件冲锋衣加入购物车」——商户真单明细按关键词回查(口语量词剥除「那件X」→「X」),解析当前在售最低价 SKU 真实回车;零命中/已下架/多命中(GROUP BY spu_id 防同 SPU 标题漂移假双候选)一律如实回复,已退款/取消单排除(与排行/资金口径一致)。
- **指标×导购确定性快轨(planner)**:「看看GMV多少,顺便推荐卖得好的」——排行子任务(rankingMetric 词族映射,与 METRIC_REGISTRY 5 键同名)+ 导购子任务确定性组装,零 LLM 拒答面(A7 偶发拒答从根上消失);订单动作快轨尾追复合偿付(指标×导购双命中才追排行,「那鞋销量不行」不凭空造步骤)。
- **executor 快路径**:queryProductRanking(仅认快轨 pinned 句式提取 rankingMetric,深规划带参描述落 LLM 兜底防吞参)+ checkoutCart 直配;白名单入列(规则文件同步修订特例条款)。

### 🐛 Fixes(评审抓获)

- **超卖竞态**:条件 UPDATE 替代先查后扣(READ COMMITTED 下 resolve 与扣减间库存可被并发单清空),密封测试以 racy resolve 桩复现竞态窗口钉死。
- **否定词误下单**:「我还没下单」「先不付款」「货到付款」被 _CHECKOUT_RE 命中会开出真单 —— 否定守卫前置。
- **复合吞(结算分支)**:「删掉背包然后结算下单」曾带着不要的商品直接开单 —— 删除/加购动作在场让位,结算分支不吞半。
- **快轨劫持**:指标轨排除族补 order_status/order_query(「查下订单顺便推荐卖得好的」不得吞订单半);导购词收紧去「款式/好看的」(「滞销款式」纯指标轮不得被塞导购子任务)。

### ✅ 验证 (Verification,如实)

- TDD 红灯先行:engine pytest **582 passed**(+21,零回归)、gateway 121 passed、ruff 双服务干净、promptfoo 双套件 56/0 + 8/0 与基线全对齐。
- 实弹:「把我订单里的冲锋衣加入购物车」→ 历史单商品按当前货架价 ¥1299 回车;「把购物车里的东西结算下单」→ 真单 AURORA-ORD-2026-5320(5 行明细 ¥4555,收货地址自动取 2.6.19 建的杭州默认地址,库级对账全对);「看看上个月GMV多少，顺便推荐下卖得好的」→ 真数据 GMV 排行(6495/4495/2697 与订单聚合一致)+ 导购双办妥零拒答。
- 已知限制如实记录:清车在 DB 事务提交后执行(崩溃窗口极小;条件扣减防超卖,重结算会二次扣减为独立订单)。

---

## [2.6.19] - 2026-09-12 (merchant 全意图真实操作验收:16 探针全绿 + 改址链路三症修复)

用户指令「在 merchant 真实操作聊天各种意图输入看结果是否对」——16 探针全意图验收,每笔带数据库对账(查单对真单状态/退款走审批门/建地址行级核验/排行对订单聚合/加购对 Redis/审批后闭环核验),脚本与结果:`.scratch/address-order-bug/merchant_intent_acceptance.py`(gitignored)。

### 🐛 Fixes(验收抓出的三个真缺陷)

- **改单地址 SQL 列名断裂(全量订单不可用)**:`change_shipping_address` 的 UPDATE 写不存在的 `address` 列(orders 真实列名 `shipping_address`)——任何单都炸并被 catch 吞成「处理失败」,merchant 真单连改的资格都没有;修复:engine 单改用 `shipping_address` 列,merchant 真单跳过引擎写(表里本就无此行)直接商户镜像写穿。
- **「退了/退掉/退还」不在退款词表(资金句误路由)**:「退了订单 AURORA-ORD-2026-9094」被判定 2 路由成查单只回状态;补入 REFUND_KEYWORDS_RE,资金句回归结构化精判→退款管线。连带面:词表扩容后判定 3 关键词分支会把「导购+退款」复合句吞成单退款——`money_action_yielded` 标记同闸(规则层已判「资金词在场但意图非资金」时判定 3 让位)。
- **高价值改址完全绕过 HITL**:技能快轨对 execute_order_action 直接传 is_approved=True,¥100 红线形同虚设;修复:技能内 >¥100 建 changeShippingAddress 审批工单并如实告知等待审核 + **恢复计划随 result.taskPlan 带回**(handle_immediate_bypass 新增透传参数)——run_agent 回合收口以 result.task_plan 覆盖 TaskMemory,不随行则挂起计划被 bypass 空计划冲掉,审批通过 resume 无计划可恢复(实弹抓获:approve 成功而地址未变)。审批通过 → HOT-RESUME 复用 → executor 快路径确定性执行,全闭环实弹验证:批准后 merchant_orders.shipping_address 真实变更为上海新址。

### ✅ 验证 (Verification,如实)

- TDD 红灯先行:engine pytest **561 passed**(+7:改址列名/merchant 跳过引擎写/退款词表/高价值 HITL 工单/低价值直执行/恢复计划随行),gateway 121 passed,ruff 干净。
- 实弹验收 **16/16 全绿**:导购(货架背包 3/3 命中)、语义检索(口语→睡袋)、单单/列表/未发货查询(与 merchant 状态逐笔对账,列表 10/10 真实单号含卡片)、退款(未越权+审批工单)、改址(审批工单)、建地址(行级核验,手机号脱敏落库)、查地址簿、销量排行(订单聚合 top3 全命中)、咨询直答、转人工(工单)、超范围(不编造天气)、加购(Redis 对账)、数量多品类;审批后真退款闭环(REFUNDED 落库)+ 审批后真改址闭环(新地址落库)。

---

## [2.6.18] - 2026-09-12 (多意图不打断一期:「建地址+下单」不再被反问劫持 + 资金动作一票优先 + 地址簿能力落地)

用户实报(diagnosing-bugs + 11 探针多意图实弹矩阵 + to-spec → implement 全流程):「创建新地址 张伟 13800138000 北京市…并下单极光防晒短袖寄到新地址」被反手索要订单号——既没建地址也没下单。11 探针矩阵钉死四层根因:①缺槽反问短路(任一意图——哪怕 secondary——缺槽,整轮变反问,planner 复合编排全被跳过);②资金动作被单技能快轨静默吞(「退了订单9081,然后推荐跑步鞋」整句进导购);③意图词表缺口(10 类目无地址簿管理,LLM 落 general_query 后编造「已发货联系快递员改派、转寄费自理」假政策);④`ORDER_ID_RE` 裸数字分支把手机号当单号。spec: `.scratch/multi-intent-no-interrupt/spec.md`(gitignored)。

### ✨ Features

- **address_manage 意图(metric_query 先例)**:规则层产出(prompt_category=None,零分类器 prompt 变更、零 promptfoo 类目基线重钉)。检测器 `detect_address_manage`(创建形/查询形双正则,显式 ORD- 单号在场让位订单域)+ 中文地址解析 `parse_chinese_address`(直辖市 province=city 同名/省→市→区/区解析不出宁可诚实反问严禁瞎猜落库)+ 判定 1.6 纯建/查地址零 LLM 直通(`address_manage_precheck` 留痕)+ Step3 复合注入器(建地址+下单等复合形提为 primary,general_query 兜底族丢弃)+ planner 单意图快轨直达 saveUserAddress/getUserAddresses 子任务。
- **executor 快路径 + 白名单**:saveUserAddress/getUserAddresses 进 executor 确定性快路径(`_save_address_args` 六字段全有才命中)与白名单基座 `_base_executor_tools`——实弹抓到不入列的代价:子任务空转给通用 LLM 步骤执行,**未调工具即宣称「已成功保存」,表 0 行**(幻觉成功,坏例池 claim_mismatch 类)。
- **深规划「尽力而为」规则(rule 7/8)**:多意图请求为每个可执行意图规划子任务、缺槽的以恰好一个 ask-user 步骤收口,严禁静默吞;下单诉求严禁规划 createOrder,改规划 addToCart + 购物车卡结算指引。

### 🐛 Fixes

- **缺槽反问收窄(两处同口径)**:规则层 `slot_clarification_fastpath` 复合候选形(MULTI_INTENT_CANDIDATE_RE 补「然后」「并」裸词)不反问;结构化层 `_should_clarify_first` 仅 primary 缺槽且无「非咨询族且槽位齐备」营救意图时反问——secondary 缺槽不再劫持整轮(A1:分类器抽槽全对,却因 secondary 缺单号全场陪葬),parsed 携带 missingSlots 注记进 planner。
- **资金动作一票否决**:`_try_skill_fast_track` 入口 + 单意图高置信终局双闸——输入命中资金词族(退款|退货|退还|退了|退掉|换货|申请售后)而非售后域技能/意图时让位 Step2/3 精判并 `money_action_veto_yield` 留痕;判定 2/3 关键词分支同闸(「查订单把没发货的退了」的查单词曾独走终端吞掉退款半)。
- **手机号/假单号防污染**:`ORDER_ID_RE` 裸数字分支负向前瞻排除 `PHONE_SHAPE`(1[3-9]\d{9},共享常量防漂移);结构化层抽取的 orderId 不过宽松正则即剥除并补缺槽注记(「订单9081」尾缀曾被当单号,执行器未调工具即宣称退款成功)。
- **createOrder 假单工具摘除(executor 面)**:写 demo 表+硬编 shipped+编造运单号,零生产消费方,从工具注册面下线(服务方法留测试/种子)。
- **A7 GMV 拒答波动**:非本轮引入(路由与本轮改动零交集,deep planner 对指标问句的拒答倾向系 2.6.15 已知残留),如实记录不掩饰。

### 📋 Docs/Ops

- agent-engine.md §1.3 如实扩员:规则直通前置登记 metric_query/address_manage 两成员(检测器双词族锚定,错判代价近零,词表缺口下 LLM 仲裁层反而必然误判)。
- promptfoo 运维注记:provider 宿主 python3 缺引擎依赖(redis/langgraph),对照/钉定需 `PROMPTFOO_PYTHON=services/.venv/bin/python`;注册表 parity 测试 14→15 档对齐。

### ✅ 验证 (Verification,如实)

- TDD 红灯先行(纯函数缝 + Step3 桩法缝,先例 test_profit_ranking_precheck/test_step3_consult_demote):engine pytest **554 passed**(2.6.17 基线 502 + 52 新增,零回归)、gateway 121 passed、ruff 双服务干净、promptfoo 双套件 56/0 + 8/0 与基线全对齐(unified 意图用例经生产瀑布真跑,triage 规则层变更未漂移基线)。
- 实弹矩阵复跑(11→8 探针):A1 建地址真落库(user_addresses 行级核验)+加购确认+新地址结算指引三段齐全;A3 列出 7 笔真实未发货单号再问退哪笔;A4 推荐加购+诚实结算指引(不再规划假单);A6 诚实查无 9081+同类推荐;A11 地址真创建。对照组 A8(问单号+主动答政策)、A10(条件式加购)不回归。评审抓获并修复:planner 快轨未限单意图(A1 复合被砍半)、资金否决未落真实让位、快路径无处理器幻觉成功——均以红灯测试钉死。

---

## [2.6.17] - 2026-09-12 (多品类连词检索修复:「裤子和 衬衫」裤子被吞 + 数量语义)

用户实报(diagnosing-bugs 全流程):「我想买几件裤子和 衬衫推荐一下」只回衬衫 3 款;「我要2个商品」数量被无视。

### 🐛 Fixes

- **连词「和/与」进词元分隔符**:旧切分器把「几件裤子和 衬衫」连成死词元「几件裤子和」(ILIKE 永远落空),只剩衬衫命中——裤子被吞的直接根因。⚠️「跟」严禁入列(高跟鞋/跟妆会被劈开)。
- **数量前缀剥除**:「几件/2个/三条…」逐块剥,「几件裤子」才算干净品类词;「三合一」不匹配前缀模式不受扰;尾缀语气字(都要/吧/呢…)仅剥长块 len>2(「衬衫都」→「衬衫」,「成都」两字不动)。
- **多品类词元轮转配额**:词元 ≥2 时逐词元各取 top-limit 后交错合并去重——价格单序会在小 limit 下让贵品类全灭(limit=2 全是衬衫);库不可达立即中断跳过单查交给既有降级链(严禁 N 词元 N 次失败连接)。
- **导购数量语义**:「我要2个/三个/4个商品」显式数量 → 推荐 N 款(中文数字映射,上限 8),「几件」或未提维持默认 3。

### ✅ 验证 (Verification,如实)

- TDD 红灯先行(纯函数缝 + 密封货架集成缝复现用户原句):engine pytest **502 passed**(2.6.16 基线 492 + 多品类套件 10,零回归)、gateway 121 passed、ruff 双服务干净。实弹(网关重启):用户原句 → 慢跑裤+皮肤衬衫+工装裤双品类交错;「我要2个商品,裤子和衬衫都推荐」→ 正好 2 款(裤 1 + 衬 1)。双轴评审批:中文数字静默丢弃(两个/三个→limit 3 空过,改四个抓真红)、「和牛/成都」类误伤边界(跟禁入列/尾剥限长块)、「都」尾剥、不可达 N× 降级延迟、预编译正则提常量。

---

## [2.6.16] - 2026-09-12 (成本价数据工程毛利回归 + 售后凭证会话历史回溯 —— ADR-0003)

ADR-0002 两个二期项一个版本收口(grill 一轮四问「按照推荐」)。

### ✨ Features

- **成本价双层落库(Q1)**:merchant_skus.cost_price(当前采购进价)+ merchant_order_items.cost_at_purchase(成交时进价快照),`ADD COLUMN IF NOT EXISTS` 追加进 `_MERCHANT_DDL` 幂等生效;seed 进价按 SKU 编码 crc32 从 42%~52% 系数调色板确定性推导(跨进程可复现,注明演示数据边界)。
- **毛利/毛利率指标回归(Q2)**:gross_profit + margin_rate 恢复进 METRIC_REGISTRY,口径为成交快照精确值(Σ 量×成交价 − Σ 量×快照进价,非估算);统计口径消歧组回 5 键;`_REMOVED_METRICS` 删除;排行条目恢复 grossProfit/marginRate(前端可选渲染零改动);消歧组指标键运行时查表,严禁手抄字面量漂移。
- **售后凭证会话历史回溯(Q3)**:`get_thread_evidence_images` 直查本会话 user 消息 image_urls(newest-first、跨消息去重、上限=视觉上限);凭证注入升级 state 驱动异步——本轮有图优先(严禁额外查库),本轮无图回溯历史,两者皆无原样返回。

### 🐛 Fixes(实弹 + 双轴评审)

- **毛利排行被两层 LLM 拒答**(实弹三连拒):triage 分类层与 planner 规划层都把「利润」当后台敏感数据——triage 判定 1.5 规则前置(`PROFIT_RANKING_RE` 利润词×排行词共现直通 metric_query,arbitration_reason 落库可审计,确定性规则不触碰 promptfoo LLM 基线)+ planner 提示词补经营口径合法性条款(严禁拒答为「后台报表」或改道导购)。
- **成本假精确风险**(评审):cost 求和去 COALESCE 0——列 NOT NULL,漏写快照的明细报错可见而非毛利虚高呈精确;三处陈旧注释/文档串(还写着「毛利已移除」)对齐 ADR-0003;名不符实测试正名(退款件成本排除由断言直接证明)。

### ✅ 验证 (Verification,如实)

- engine pytest **492 passed**(2.6.15 基线 484 + 新增 8)、gateway 121 passed、ruff 双服务干净;重播种后 92/92 SKU、47/47 明细全带成本快照。实弹:净毛利排行冲锋衣 No.1(毛利 3,507.3 / 54.0%)、毛利率排行速干衬衫 No.1(58.0%)——口径不同冠军不同,纯真数据;带图轮后无图退款,审批载荷实弹携带轮 1 凭证(历史回溯命中)。ADR-0003 验证段已回填。

---

## [2.6.15] - 2026-09-12 (售后凭证落票 + 排行真销量源 + 热销解禁 + 商户目录扩容 —— ADR-0002)

2.6.14 收尾留档三项同根源遗留(数据不在该在的地方),grill-with-docs 两轮八问逐项裁决 + /to-spec 发布(.scratch/aftersale-evidence-real-sales),TDD 落地;实弹三抓三修。

### ✨ Features

- **售后凭证落票(ADR-0002 Q1/Q2)**:`after_sale_tickets` 加 `evidence_urls` JSONB(0009 迁移),`applyAfterSale` schema 加 `evidenceImageUrls`,executor 层程序化注入(严禁指望 LLM 抄 URL):applyAfterSale 落工单凭证列,processRefund 凭证随 HITL 审批载荷让人工审批员看图;上限对齐视觉常量;落库失败诚实报错严禁假「已提交」。
- **排行换商户真销量源(Q3)**:`queryProductRanking` 改商户真订单聚合(merchant_order_items × merchant_orders,**排除退款/取消单**,明细按 SPU 预聚合子查询);毛利/毛利率随成本数据缺位整体移除(消歧胶囊组 5→3),被移除指标(含中文别名)诚实报错;manager_id/businessId 过滤随本地演示表路径退役。
- **热销解禁(Q4/Q7,数据条件禁令)**:有真聚合兜底的「🔥 热销商品」入口置顶(点击文本「按销量查一下热销商品排行」——实弹验证裸「热销」会被导购词表截获),品类 chip 自身仍禁热度词;chips 上限 6→8;导购推荐卡「热销推荐」改「为您推荐/店长精选」、编造 metricScore(99-idx*5)拆除。
- **商户目录扩容(Q5/Q6/Q8)**:9 品类 30 SPU / 92 SKU(新增 衬衫/配饰/运动配件,衬衫即产品最初点名品类);27 笔演示历史订单行项目从目录派生(单一事实源),状态 PAID7/SHIPPED13/DELIVERED8/REFUNDED2、日期散布最近 60 天、17/30 SPU 有销量长尾诚实零——聚合永远运行时真算。

### 🐛 Fixes(实弹三抓 + 双轴评审)

- **排行 JOIN 扇出**(实弹):1 SPU × N SKU × M 明细三路直连笛卡尔放大,冲锋衣 5 件卖成「量30/GMV 38,970」——明细预聚合子查询 + 双 SKU 密封用例钉死。
- **售后工单从未真正落库**(实弹):`order_id` 外键指向本地 orders,商户真单售后插不进去且异常被吞返回假 `success:True`——0010 迁移去 FK(订单双源现实)+ 诚实报错,真 DB 直调验证 evidence_urls 落库。
- **导购推荐卡冒充排行卡**(实弹):rankingMetric=recommendation 误触发统计口径消歧组;消歧组只认真源指标。
- 双轴评审批:seed `days_ago` 死数据(INSERT 补 created_at 散布)/共享密封容器卫生(异形 DDL 对齐、reader patch 泄漏恢复、FK 卡 TRUNCATE)/消歧组「我负责的」文案退役/processRefund schema 补凭证声明/证据上限统一引用视觉常量。

### ✅ 验证 (Verification,如实)

- engine pytest **484 passed**(2.6.14 基线 465 + 新增 19)、gateway 121 passed、ruff 双服务干净;Alembic 0009/0010 已应用;商户库重播种 30 单日期散布 2026-07-17~09-10。实弹:热销排行真数据(T恤 7 件 No.1 / 冲锋衣 GMV 6,495=5×1299,退款排除);带图售后审批载荷实弹携带凭证 URL + 工单 evidence_urls 直调落库验证;「看看衬衫有什么商品」4 款真实命中(库存=SUM(SKU) 正确);热销入口 + 品类 chips 上限 8;推荐卡「为您推荐」零编造。设计过程:ADR-0002 + spec(.scratch/aftersale-evidence-real-sales)落盘,CONTEXT.md 术语与 README 计数同步。

---

## [2.6.14] - 2026-09-12 (场景化快捷回复:固定四件套退役,按意图出组 + 「查询未发货的订单」能力补齐)

产品在退款反问轮与商品推荐轮提出「快捷按钮按情况提供」;grill-with-docs 两轮六问逐项裁决(ADR-0001),TDD 落地。

### ✨ Features

- **场景化快捷回复(ADR-0001)**:card_synthesizer 收编基座裁决(域卡片优先作基座,run_agent short-circuit 拆除),按本轮已分类意图出组——refund/order_return → 退款四键(查询最近的订单/查询未发货的订单/上传商品瑕疵照片/呼叫人工客服;场景内撤「申请退款」,用户已在流程中);shopping_guide → 品类 chips(点击「看看{品类}有什么商品」直达导购);其余 → 通用四键(查询我的订单/逛逛商城/申请退款/人工)。旧「查询物流进度」并入订单查询(同一意图同一出口),固定四件套整体退役,前端零改动。
- **品类 chips 只认真货架**:`get_shelf_overview` 实查(仅购物轮查库,失败退通用组严禁编造),带真实在售款数,文案严禁「热销/卖得好/爆款」——2.6.8「商户货架无销量列」铁律从文本输出延伸到 UI 交互层(死按钮禁令)。
- **未发货过滤能力**:`list_user_orders` 加 `shippingStatus`(UNSHIPPED=仍在等待出货,排除 refunded/cancelled——实弹修正 CUST-8801 两笔 REFUNDED 单曾被算成未发货;SHIPPED/DELIVERED 精确匹配;非法值诚实报错严禁静默全量;商户真单/engine 本地表两路同走 `_apply_shipping_filter` 纯函数防漂移),工具 schema enum + executor 提示词 + 快路径三处同语义。

### 🐛 Fixes(双轴 code-review 掀出,一并修复)

- Temporal 双模路径残留旧 short-circuit,域卡片轮仍不挂场景组 → `temporal/activities.py` 与 run_agent 同一合成接线,两路严禁漂移(2.6.8 先例)。
- 技能自带 quick_replies(破损照片消歧组)与场景组会同屏双胶囊 → first-wins:技能自带行原样保留,场景组让位。
- executor 快路径硬编码 `args={}` 吞掉 shippingStatus → 快路径与 LLM 路径同语义(描述/输入含未发货语义即传 UNSHIPPED)。

### ✅ 验证 (Verification,如实)

- engine pytest **465 passed**(2.6.13 基线 441 + 新增 24 零回归:场景组 13 / 未发货过滤 8 / 快路径 3),ruff 干净。实弹(网关重启):退款反问轮 → 退款场景组;「查询我未发货的订单」→ 诚实空(3 单全 SHIPPED/REFUNDED,无一错报未发货);「看看商城有什么商品」→ 6 真品类 chips(各 3 款,对账 18 SPU);点击「潮流鞋靴」chip → 品类过滤 3 款鞋靴;咨询轮 → 通用组。设计定案落 docs/adr/0001,术语表补 CONTEXT.md「Chat Cards & Quick Replies Subsystem」。

---

## [2.6.13] - 2026-09-12 (加购序数越界诚实反问:「把第四个加入购物车」不再错加第 1 款)

### 🐛 Fixes

- **加购分支序数越界守卫(用户实报)**:导购推荐 2 款运动鞋后说「把第四个加入购物车」,系统把第 1 款(Vibram 老爹鞋)错装进购物车并播报「已在购物车中,本次未重复加入」。根因:加购分支解析出 target_index=3 后候选仅 2 款,两个 `< len` 判断都不成立,序数静默作废落到 `candidate_products[0]` 兜底 —— 与删除/改量分支 2026-09-06 已修的「越界序数静默落兜底链」同类症状,加购分支漏了同款守卫。修复:序数解析不出有效目标时诚实反问(列出全部候选 + 未加入任何商品),购物车零触碰;实报输出与回归测试逐字复现(TDD 红灯在前)。
- **序数词表扩到十 + 多位数字**:`一~五/1~5` 旧词表外,「把第六个加入购物车」根本不进序数分支、同样静默落第 1 款 —— 词表扩至 `一~十/多位数字`,删除/改量分支的越界守卫自动同步受益(「删除第六件」此前会落到 lastModified/首款兜底链);`_ordinal_to_index` 助手统一换算,顺带修掉「第10件」被单字符截断成「第1件」的隐性错位。
- **词表外大序数宽守卫**:「第十一/第100」等超表序数经 `_ORD_ANY_RE` 存在性判定,同口径诚实反问,不猜不装。

### ✅ 验证 (Verification,如实)

- engine pytest **441 passed**(2.6.12 基线 437,+4 零回归:越界反问/词表外反问/界内第2款正常入车/5 款候选第4款正常入车),购物车全域 7 套件 50 过,ruff 干净。实弹(网关重启后复走实报对话):「好的运动鞋」→ 2 款推荐 →「把第四个加入购物车」→「本次推荐只有 2 款商品,没有第4款,未加入任何商品」+ 候选清单;「把第二个加入购物车」→ 正确加购徒步登山鞋(顺带印证实报中「已在购物车 x1」是演示用户 CUST-8801 购物车的真实遗留状态,非编造)。

---

## [2.6.12] - 2026-09-12 (商品排行卡白屏收口:检索结果误装排行卡 + 推荐卡编造 GMV 拆除)

前端实报 `ProductRankingCard.tsx:74` 抛 `Cannot read properties of undefined (reading 'toLocaleString')`(聊天台白屏),诊断闭环收口,顺带在同一张卡上掀出并拆除一处漏网 mock。

### 🐛 Fixes

- **根因(engine 卡合成器误判)**:排行卡判定含「subtask 结果 `products` 非空即排行卡」启发式,与 `searchProducts` 工具出参撞键 —— planner 选工具路径(非导购技能)时,检索结果条目是商户货架检索形(`id/name/price/stock`,无 `totalGmv/grossProfit/metricDisplay`),被误装成排行卡后前端读缺失字段抛 TypeError 白屏,且给搜索结果盖假「总销售额 (GMV)」头衔挂排行快捷消歧组。判定收口为只认排行签名(`rankingMetric`/步骤 id/描述含 ranking);真 `queryProductRanking` 出参恒带 `rankingMetric`,契约测试钉死不受扰。
- **前端防御性渲染**:`RankedProductItem` 排行字段(totalVolume/totalGmv/grossProfit/marginRate/metricScore/metricDisplay)改可选,`ProductRankingCard` 按存在性渲染、缺省降级「—」—— 线上任何契约违约降级为局部缺项,不再整台白屏。
- **推荐卡编造指标拆除(诚实性,同卡同源)**:`ShoppingGuideSkill` 推荐卡一直编造 `totalGmv=价格×100`、`grossProfit=价格×40%`、`marginRate='40%'`、`totalVolume` 兜底 100,前端照实渲染成「销量:100 件 • 毛利率:40% • ¥49,900」欺骗用户 —— 2.6.10 mock 清零的漏网之鱼(E2E 电池只审文本输出未审卡片载荷)。整体拆除只留真实字段(价格/现货/品类/推荐位次),对齐 2.6.8「商户货架无销量数据,严禁合成假热度」铁律。

### ✅ 验证 (Verification,如实)

- TDD 三红灯先行:前端 `renderToString` 复现原始 TypeError / engine 合成器对检索出参误装 / guide 卡编造字段断言 → 修复后全绿。engine pytest **437 passed**(434 基线 +3,零回归)、packages/ui bun test **20 passed**、admin/web 套件 **23 passed**、ruff + tsc 干净。实弹三流复测:推荐卡载荷仅真实字段、GMV 排行卡契约正常(诚实空 items=0)、检索流零卡片误装。

---

## [2.6.11] - 2026-09-12 (实测遗留三项收口:退款金额诚实化 + 降级网双层加固 + 规格问句直答)

2.6.10 全链路实测(/implement 后 E2E 电池)撞出的三项遗留,本轮 TDD 收口;双轴 code-review(Standards + Spec 并行子代理)又从修复本身掀出四处次生问题,一并修复。

### 🐛 Fixes

- **退款金额诚实化(残余①)**:`process_refund` 回执旧硬编码 `$` 前缀(人民币店渲染成美元,实测「退款金额 $1299.0」)且金额未知时兜底编造 **"$99.99"** —— 退款单编造金额比货币符号错严重得多。改为真单总额/申请额随单取值,平台 CNY 默认(显式 USD 才 $),剥不出数值如实「待确认」(`_format_amount_value` 助手,float 异常兜底);审计文案两处编造的 "$100 limit" 限额声明(代码并不知晓该值)改为如实描述(金额 + 时效窗 + "no approved HITL record"),地址变更审计/挂起文案与免签放行状态事件的 `$` 家族同批清零。**实弹复测**:9082 完整审批闭环 → 「退款金额:¥589.00」零美元符。
- **降级网双层加固(残余②)**:上游 429 重试耗尽曾以 HTTP 500 + ASGI 堆栈裸露。①`run_agent` 图调用 `except` 从仅 `CircuitBreakerOpenError` 拓宽到全异常,与熔断同形道歉降级(回复照常交付、SSE 流照常收口);②网关 sync 派发 `await task` 兜 try/except,残余异常返回诚实道歉文案而非 500;③回复产出后的三路记忆回写/任务态落库/result 事件发布全部包护 —— 答案已算出,持久化失败不得吞掉交付。
- **规格问句直答(残余③,技能面)**:`ProductInquirySkill` 新增规格问句分支(规格/尺码/尺寸/颜色/码数/参数/型号),检索首位商品命中即直查真货架 SKU 出参渲染(价格/库存/缺货如实),查无回落商品列表;非规格问句零 SKU 查询。**已知残余(如实)**:意图路由仍把「双肩包有什么规格」判 general_query(structured_llm 0.95),技能面已具备直答能力但路由未到位 —— 触达需动意图路由 + promptfoo 基线重钉,单独立项。

### 🔍 双轴审查次生修复(code-review 掀出)

- **遥测失真**:图异常降级原复用熔断旗标,session_metrics 会落 `resolved_auto`/`is_success=True` 把失败记成成功 —— 新增 `graph_error_fired` 旗标,独立落 `resolution_status="graph_error_degraded"`(is_success=False),坏例池同权入池(独立 note);`_degraded_llm_breaker_result` 更名 `_degraded_apology_result`(docstring 覆盖两种降级来源)。
- **规格错配守卫**:productId 为空串时 `query_product_skus` 条件全空会拉回任意 20 条本地 SKU 冠以首位商品标题 —— 空productId 直接回落列表形态。
- **金额解析后置风险**:`float()` 在退款 UPDATE 已 commit 之后执行,异形串("1.2.3")抛错会使已落库退款走进道歉降级 —— 统一收口 `_format_amount_value` 内兜底。
- **审计自相矛盾**:降级文案 `{total_amount or 0}` 渲染 "¥0" 与 `refundAmount="待确认"` 打架,改用已解析诚实值。

### ✅ 验证 (Verification,如实)

- engine pytest **434 passed**(2.6.10 基线 432,+2 零回归:规格直答/非规格不触达 SKU);gateway 契约套件 **121 passed**;ruff 干净。实弹:退款 ¥589.00 全链闭环;429 场景不可稳定复现,以双层代码防线 + 契约套件护航(如实记录,未实弹)。

---

## [2.6.10] - 2026-09-12 (mock 兜底清零:七处欺骗性兜底拆除,失败/查空一律诚实空或真实失败)

诊断起点(/triage + 全链路实测电池):分诊盘点定位五处残余欺骗性 mock,E2E 实测(40+ 条真实 LLM 消息)又撞出两处——「清空购物车→查看」100% 变出幻影 AJ1(`(await _load_cart(key)) or [演示车]` 的 falsy 陷阱:清空写入的 `[]` 必然落进兜底)、技能层加购 `or 899.0` 假价格(恰为已拆除的 Pegasus 假商品价)。工单 real-data-only/01,维护者裁决:演示身份体系(CUST-8801 等)保留划出范围。

### 🐛 Fixes

- **SKU 查询假目录拆除 + 商户货架接线**:`query_product_skus` 降级链重构为 **商户真货架(merchant_skus×merchant_spus,spu_code 精确/标题子串双解析)→ engine 本地 product_skus → 诚实空**;旧「查无/异常兜底 AJ1 三件套」整体退役——真店问「双肩包有什么规格」此前只能答「没有参数」(商户 62 SKU 不在命中面),现在按名直达真规格;两路出参经 `_sku_rows_to_payload` 共用 mapper 契约零漂移(skuId:商户路径取 sku_code 与导购候选/网关加购同标识,本地回退保持行 UUID)。
- **地址簿假地址拆除**:`get_user_addresses` 旧「张先生/中关村」高保真兜底退役,查无/库不可达 → `total: 0` 空列表。
- **地址保存假成功拆除**:`save_user_address` 写库失败旧返回 `success: True` + `addr_mock_` 假 ID(用户以为存上实际未落库)→ `success: False` + 可读错误。
- **购物车演示车拆除**:`get_cart_summary` 空车/缺失键一律诚实空(`itemCount: 0`),`[] or 演示车` falsy 陷阱根除;`has_cart` 过时 docstring 同步更新。
- **加购假价格双收口**:服务层 `add_to_cart` 缺价拒绝入车(899.0 兜底退役);技能层 `cart_manage_skill` 三处 `or 899.0`/初始化同步拆除透传真价,且入车被拒经 `_add_rejected_response` 如实回传、不再播报成功卡——服务层守卫不再被技能层预编价格架空。
- **RAG 假切片退役**:ContextualRAG PG 查询失败旧降级「Local Fake RAG」(内联种子切片 + 关键词拍出的假相似度 0.35/0.65/0.55)→ 诚实空,与嵌入失败降级同标准;`SEED_DOCS`/`_search_local_fake_docs`/模拟相似度整体删除(冷启动播种自 9-09 起同源读 docs/knowledge,不受影响)。
- **Admin 透视假轨迹拆除**:ThreadDeepTraceDrawer 时间线查空/加载失败旧按意图整段合成假对话(假思维链/置信度 0.985/假工单号/假顺丰单号)→ 空态「暂无历史对话消息」。

### 🧹 命名与文案

- `run_agent.py` 问候旁路 `mock_result` → `greeting_result`(内容是真实 onboarding 配置,仅命名失真)。
- `gatekeeper.py` 审批挂起文案指路「人工授权模拟面板」(admin 无此面板)→ 改指真实入口「审批与风控审计」页(与 Sidebar/Header 导航名一致)。

### ✅ 验证 (Verification,如实)

- engine pytest **432 passed**(2.6.9 基线 423,+9 零回归):新增 `test_mock_purge.py` 9 用例——SKU 商户货架接线/OFF_SALE 与查无诚实空/双库不可达诚实空/地址簿诚实空/地址保存真实失败/空车诚实空/清空→查看空车/缺价拒绝入车/RAG 库失败诚实空;TDD 先红灯(AJ1 假目录在测试中现形)后绿灯。
- ruff 干净;admin tsc 通过、biome 警告改前改后持平(4 处既有,零新增)。
- 实弹复测(真网关 4000):清空→查看 → 「0 件商品(暂无商品)」零 AJ1;「推荐背包热销」→ 真货架 3 SPU 零跑鞋(检索链零回归)。
- 已知边界(如实):「双肩包有什么规格」技能面会先反问具体商品(对话策略,工具面已按名直达);批注示例 long_memory 提示词中的 Nike/Air Jordan 系偏好抽取教学示例,非数据面,保留。

---

## [2.6.9] - 2026-09-12 (加购幻影 Nike 收口 + 检索召回三连升:词干别名 / L4 词表锚定改写 / 诚实空品类盘点)

诊断起点(/diagnosing-bugs,红灯脚本 /tmp/repro_cart_bug.py):「卖的好的短袖」推荐后追一句「把第一件加入购物车」,入车的是**不存在的 Nike Pegasus**。事故链三层——①「卖得好」措辞不在快轨触发词表,落入 structured_llm 图路径;② planner 给 executor 的是 searchProducts **工具**而非 ShoppingGuideSkill,工具路径不写 guide_context,且 `_execute_single_step_core` 对 state 的直接赋值是死写(executor_node 只回传四键),上一轮导购的 stale 候选经 run_agent 收口原样存回 TaskMemory;③ CartManageSkill 序数解析失败时硬编码 Pegasus/AJ1 假商品兜底,幻影商品入车。

### 🐛 Fixes

- **幻影 Nike 加购回归三层收口**:A. 触发词补「卖得好/卖的好」(slot_extractor SHOPPING_GUIDE 与 guide_skills `_FALLBACK_RE` 同源补词)——该措辞族回 Triage 快轨,ShoppingGuideSkill 刷新候选;B. 图路径确定性守卫:searchProducts 工具结果非空即登记 `guide_context`(与技能路径 `extra.guideContext` 同形,不依赖 planner 选工具还是选技能),且 guideContext **经返回值上行**(单步/并行两路收口,executor_node 写入图状态)——stale 候选不再跨轮存活;C. CartManageSkill 候选全解析失败时诚实反问,拆除改量(`sku_nike_aj1_blk_425`)与加购(Pegasus 假商品)两处硬编码兜底——无上下文的加购指令宁可追问,不可编造目标商品。
- **词干别名展开**:`_expand_stem_aliases` 口语统称「裤子/鞋子」→ 追加货架词素「裤/鞋」OR 词元(症状「卖的好的裤子」:货架命名「工装裤/慢跑裤/老爹鞋」四列不含「裤子/鞋子」子串,ILIKE 永远擦肩;语义档余弦 0.51-0.53 又卡 0.55 阈值下,词干路径才是确定性修法)。刻意显式小词表而非通用剥「子」——电子/种子类词剥后语义漂移;空表进空表出,浏览形判定不受影响;语义档仍嵌原始 query(阈值按原始查询定标,换表示会毁定标)。

### ✨ Features

- **L4 词表锚定改写重试**:词元+语义双空后(症状「卖的好的背心」双空即终局),`_rewrite_query_terms` 以 `get_shelf_overview()` 品类词表为锚调一次 LLM,把口语措辞映射成货架检索词元(只允许产出词表品类词或常见叫法,防跨目录自由发挥)再重试一次;`AI_MALL_QUERY_REWRITE_ENABLED` 默认开、`AI_MALL_QUERY_REWRITE_TIMEOUT_SECONDS` 默认 2.0;超时/异常/脏输出/非 dict 体一律降级空表,检索链终点始终是诚实空;产出钳制(2-6 字、≤3 个、去重、剥 ``` 围栏);纯浏览形输入不进 L4。
- **诚实空品类盘点**:`get_shelf_overview()` 在售 SPU 按品类聚合计数(OFF_SALE 不计数,spu_count DESC + category ASC 确定序),ShoppingGuideSkill / ProductInquirySkill 空分支把「调整关键词」升级为「目前店内热卖品类:背包收纳(2款)…」——剩余诚实空从冷场变成可点选的真实方向;盘点不可达优雅省略盘点段(不降级 engine 本地表,盘点描述商户店内、严禁跨目录拼数)。

### ✅ 验证 (Verification,如实)

- engine pytest **423 passed**(2.6.8 基线 397 → 本轮 423,+26 零回归):新增幻影 Nike 回归套件 `test_cart_phantom_nike_regression.py`(事故链钉死)、词干别名 3 用例(裤子召回/鞋子对称/「杯子」不通用剥子)、L4 改写 8+6 用例(接线召回/空表诚实空/开关关闭零触达/密封降级 + 纯解析围栏剥除/脏 JSON/非 dict/长度去重截断/词表空零调用/超时)、品类盘点技能面 4 用例(盘点空不编造/有盘点带真实品类/两技能同源);ruff 干净;promptfoo 不跑(eval/ 零相关引用,不动意图路由契约)。
- 既有诚实空语义用例回归确认:改写档套件级默认密封(沿 `_sealed_embed` 先例),意外进入 L4 分支的用例得到降级空表,行为与封桩前一致。

---

## [2.6.8] - 2026-09-11 (商品检索假货收口:接通商户真货架 + 拆 mock 兜底 + 语义召回补位)

诊断起点(/diagnosing-bugs):门店聊天输入「推荐背包热销」,回复却是 3 件 Nike 跑鞋。根因两层——① `search_products` 以整句做子串匹配(`name ILIKE '%推荐背包热销%'`),NL 措辞永远命中不了任何商品字段;② 查无时 `filtered or MOCK_PRODUCTS` 欺骗性兜底把整个假目录(3 件 Nike)冒充「热销推荐」全量返回。B 档先改诚实过滤暴露真缺口:18 SPU/62 SKU 真货全在 agent_merchant 独立库,engine 侧只看本地 products 表(5 行,无背包)。

### 🐛 Fixes

- **检索降级链重构(L3)**:`search_products` / `compare_products` / SPI `search_products` 统一走 **商户真货架(`agent_merchant.merchant_spus/skus`,经 `order_domain._merchant_reader_engine` 跨库只读)→ engine 本地 products 表 → 诚实空**;单商户现实下全租户统一路由(含 ecommerce,商户表无租户列)。词元 OR ILIKE 四列(title/subtitle/**category**/description——SPU title 是「双肩包」不含「背包」,品类列才是命中面)+ `status='ON_SALE'` 过滤 + `HAVING MIN(k.price) IS NOT NULL` 常驻(无 SKU SPU 展示价 NULL:PG ASC 排 NULLS FIRST 且 `float(None)` 炸);展示价=MIN(sku.price)/库存=SUM(sku.stock) 与网关 `_spu_to_product` 同语义。**跨库读严禁 from-import 导入期绑定**(运行时经 order_domain 模块属性查表,测试整体替换模块属性注入密封容器引擎)。
- **假货整体拆除**:「要背包给跑鞋」的欺骗性兜底源头 `MOCK_PRODUCTS`(3 件 Nike 假目录)整体删除;`compare_products` 硬编码 Nike 拼接与点名 Pegasus/Invincible 文案一并拆除,话术不得点名检索结果里不存在的商品。库可达但查无必须诚实空,严禁跨目录补货。
- **L1 导购词族补齐**:`_GUIDE_WRAPPER_TERMS` 追加评价/热度修饰词族 18 条,一律**短语形**——「的」是分隔符但「好/高」不是,「比较好的帐篷」剥裸词「比较」会残留『好』词元(OR 匹配拉入无关商品);长序替换内建使「性价比高」先于「性价比」消费;补「有什么」修复词表只有「有没有」的浏览形漏判不对称。
- **SPI 改道**:`LocalDbSpiAdapter.search_products` 经 `MallDomainService` 统一检索链,出参七键契约零漂移,ProductInquirySkill 零改动。

### ✨ Features

- **L2 语义召回补位**:商户货架词元查空且原始 NL 非空时,对硬过滤候选池(status/category/maxPrice 先行挤出池)做 bge 余弦 top-k,命中按相似度 DESC——口语措辞(「野外露营睡觉用的」)不再空手而归。阈值 **0.55 系真 bge-small-zh 实测定标**(首版 0.6 实测全灭:正例落 0.56-0.58、无关品类 0.36-0.45,bge-small 余弦绝对值整体偏低),与 RAG 直答同档。SPU 向量进程内缓存按文案 sha256 失效(商户改标题/卖点下轮自动重嵌,无需通知 engine);嵌入走 `get_embedding_model()` 既有串行护栏(防 2026-09-05 双线程 SIGSEGV);嵌入异常/不可用降级诚实空绝不阻断;`AI_MALL_SEMANTIC_ENABLED=0` 一键关。

### ✅ 验证 (Verification,如实)

- engine pytest **397 passed**(2.6.7 后基线 332 → B 档 373 → 本轮 397,零回归):新增 `test_merchant_catalog_reach.py` 16 用例(密封商户库:症状钉死/OFF_SALE/maxPrice=min SKU 价/降级链/技能端到端/SPI 契约/诚实空不跨目录/浏览形/多词元 OR + 语义 6:补位命中/阈值下诚实空/缓存文案哈希失效重嵌/嵌入故障降级/开关关闭零触达/硬过滤先于语义),`test_mall_search_terms.py` 重构 16 用例(词元单测 + engine 降级分支,商户 reader 抛异常桩密封消除宿主 env 非决定性);ruff 干净;promptfoo 不跑(eval/ 零 searchProducts 引用,不动意图路由)。
- 实跑真商户库(18 SPU/62 SKU):「推荐背包热销」→背包收纳 3 SPU(¥259/499/829)零跑鞋;「比较好的帐篷」→露营帐篷;「野外露营睡觉用的」→睡袋 0.58+帐篷 0.56(语义补位);「户外防晒防雨的外套」→硬壳冲锋衣 0.57(次高 0.52 挡掉);「Pegasus 41」「滑雪板」→诚实空(假鞋时代结束)。
- 已知边界(如实记录):热销排序不做(merchant 库无销量列,全仓亦无 sales_volume),词元/浏览路径排序 min_price ASC 系已文档化限制;其余 TS 基线 mock(query_product_skus/tracking/reviews/演示车)不动。

---

## [2.6.7] - 2026-09-10 (误退事故两层收口:带图轮次豁免文本去重 + 单号信任边界;会话时间线排序锚修正)

诊断起点(/diagnosing-bugs):用户重发「坏了」+ 破损投诉图(图内明示外店单号 ORD-77777),机器人对**本店真单** AURORA-ORD-2026-9081 误起退款审批。vision 实弹输出依旧完全正确(`extractedOrderId=ORD-77777` / severe 0.95)——2.6.3 的 OCR 消费修复本身无恙,错在成果被两道旧闸联合短路:

1. **重复提问拦截器吞新证据**:Step 0 文本去重只比 `input == 上一轮用户文本`,当前轮图证与 Step 0.5 刚算出的 `vision_order_id` 被完全无视 → `duplicate_bypass` 逐字重放修复前(pre-OCR 消费)的旧消歧卡,引导用户挑本店真单;intent_logs 佐证 `duplicate_bypass(rule)` 后一轮即 refund 审批落库。
2. **历史回填单号冒充已确认**:通用 `extract_order_id` 反扫历史把旧消歧卡里的本店真单回填进 slots,旧代码直接 `_set_target_order_id` → refund 判定 fused 的 confirmed 通道与视觉消歧闸双双短路 → vision OCR 失效的轮次(GLM 结构化输出非确定性失败降级启发式、extractedOrderId 为空)直接对历史单自动退款。

### 🐛 Fixes

- **带图轮次豁免文本去重(`triage/intent_triage_engine.py`)**:图证即新证据,与 `is_operational_action` 同为去重豁免闸——否则带图重发会在图证被消费之前就把会话关成过期答复的重放。纯文本真重复照旧重放(对照组钉死,不过度修复)。
- **单号信任边界(同文件)**:slots.orderId 区分来源,优先级定谳 **文本显式 > TaskMemory 已确认 > 图内 OCR > 历史回填**;历史回填值留在 slots 供查询类续聊(ORDER_QUERY 快轨),不写入 order_context 冒充已确认、不充当消歧闸的已解析通道。Step 1.6 消歧闸的 `order_id_resolved` 同步改喂文本通道单号(谓词自述即「text channel」,旧代码传 slots 违反自述,历史回填值借道闸门短路消歧)。
- **会话时间线排序锚(`gateway_py/conversation_repo.py`)**:merchant 聊天记录顺序错乱——messages.timestamp TEXT 混格式(网关 naive 墙钟 / 引擎 UTC 带偏移)字符串序跨格式必乱;列表排序与 LATERAL 末消息同锚改 `created_at`,契约测试钉死混格式线程「问→答」对序。

### ✅ 验证 (Verification,如实)

- engine pytest **332 passed**(基线 329 + 事故钉 3:带图重发不重放且 OCR 消费 / OCR 失效 × 历史回填必须消歧不退款 / 纯文本真重复照旧重放),ruff 干净;网关契约套件 **121 passed**(2.6.6 基线 120 + 时间线对序 1)。
- 网关实弹回路(播种带 `-i` + 行数断言):事故线程形状逐字回放「坏了 + 破损图」→ 不重放、不自动退款,图内 ORD-77777 照常消费、幽灵单前置拦截诚实报错;全新线程同输入同样 GREEN。
- 已知残余(如实记录):多意图分支 `_set_target_order_id(state, primary_order_id)` 仍可把回填单号种进 order_context 影响下一轮(需复合多意图输入才触发,不在事故链上,留观)。

---

## [2.6.6] - 2026-09-10 (2.6.5 收官遗留三清:DELETE /threads 补齐 + admin 创建流收 onboardingConfig + 回落语义措辞同步)

用户指令「遗留 处理了」—— 收口 2.6.5 交付报告中的遗留项:web 侧栏删线程按钮自 TS 时代调用至今服务端恒 405、admin 引导配置仅编辑态可设(新建租户须先建后编辑两步走)、server-gateway.md §1.1 回落语义措辞与评审修订后的实际行为脱节。

### ✨ Features

- **DELETE /api/chat/threads(契约 43→44)**:`conversation_repo.delete_thread` 属主严格等值守卫(无主线程 403——顾客列表本就看不到,不开放顾客删除;跨用户 403;查无 404,threadId/userId 必填缺省 422);同一事务删除 threads + messages + task_memory(POST 接受客户端自报 threadId,同 id 重建不得复活旧任务态);**审计类记录(pending_approvals/intent_logs/session_metrics 等)刻意保留**——审批与遥测是平台审计资产,不随顾客删线程蒸发;web 确认弹窗文案与现实对齐(不再谎称抹除审核单据/日志度量),删除后活动线程回退逻辑保留。4 条契约测试(级联删除/必填/非属主 404)。
- **admin 租户创建流收 onboardingConfig(消除「仅编辑态」边界)**:`POST /api/tenant` 的 `TenantCreateIn` 新增 `onboardingConfig`——与 PUT 同语义的服务端 `validate_onboarding_config` 校验(错形 400 诚实失败且租户不落库),tenant_configs 两分支落库(既有行合并式仅携带时写、新行 INSERT 带列),未携带保持未配置(首访走平台默认);admin 表单 JSON 文本域创建/编辑两态同渲染(文案区分:新建留空 = 不写入、编辑留空 = 不修改、`{}` = 显式重置),JSON 解析提升至提交前(两分支共用),createTenantApi 补 `res.success` 检查(400 经 throw→alert 可见,不再静默假装创建成功)。3 条契约测试(创建回读等值/错形 400 不落库/未携带回 null)。
- **rules 措辞同步**:`server-gateway.md` §1.1 引导行回落语义改为评审修订后的行为(配置存在含 `{}` 即权威;welcome_message 列仅中继 NULL 存量租户),路由计数 43→44,补删线程条目与创建流语义;CLAUDE.md §2 契约计数同步。

### ✅ 验证 (Verification,如实)

- 网关契约套件 **120 passed**(2.6.5 基线 113 + 删线程 4 + 创建流 3),ruff 两服务干净,web/admin tsc + biome 干净。
- 存量旧线程无 welcome 行维持设计决策不动(空时间线如实呈现,非缺陷)。

---

wayfinder 地图(`.scratch/new-user-onboarding/`)六张工单一次落地。此前新顾客看到的欢迎语是 web 前端写死的 `DEFAULT_ASSISTANT_MESSAGE`(提 LangGraph/记忆系统等内部术语、零租户品牌、零能力入口),刷新即丢、不落库;引擎问候旁路又持另一套自我介绍——两套话术并存。

### ✨ Features

- **onboarding_config 配置底座(A)**:`engine_py.onboarding` 单一来源——schema(welcomeText≤500/returningGreeting≤200/quickRepliesTitle≤50/quickReplies 1-8 按钮带 action+payload)与平台默认三段式文案(身份→3 能力主题→单一召唤,按钮 3-5 个动词开头、转人工固定末位);回落语义(评审修订):**配置存在(含 `{}` 显式重置)即权威**,缺失字段直接回落平台默认渲染 {brand},`welcome_message` 列仅中继 onboarding_config 为 NULL 的存量租户(该列首个消费方)——与 PUT「携带即整体覆写」及 admin「`{}` = 重置平台默认」承诺自洽;DB 异常回落平台默认冷启动不炸;`tenant_configs.onboarding_config` JSONB 列(Alembic 0008,幂等护栏)+ aurora 种子带品牌化配置。
- **GET /api/chat/threads 会话列表(B,契约 42→43)**:web 侧栏历史恢复的真实数据源;`list_user_threads` 严格 `user_id` 等值(严禁 ILIKE 模糊——跨用户泄漏防线),LEFT JOIN LATERAL 最后消息摘要,updated_at DESC 服务端固定封顶 50(不对客户端开放翻页参数);同批钉 4 条契约测试。
- **建线程引导行落库(C)**:POST /threads 新建成功(`created` 标记)后服务端判定首访(`list_user_threads(limit=2)`,per user×tenant)——首线程写完整 welcomeText + quick_replies 入口卡(cards JSONB),回访写一行轻问候;确定性消息 id `welcome_{threadId}`/`greet_{threadId}` 双护栏防重放双写;引导行只归属真实 userId(匿名线程不落,不冒认演示账号);引导行失败不阻断建线程(契约测试钉死)。**写所有权特例**:assistant 行归引擎,但引导行是网关写入的刻意例外(仅建线程时点,docstring+契约测试钉死)。
- **问候旁路同源化(D)**:run_agent 身份问句表 × triage 时段问候表并集收口为 `QUICK_GREETING_WORDS` 单一来源(GREETING_RE 程序化派生,两层永不漂移;原表带空格词条在剥空白规整下本是死词条,统一规整后形态);极速旁路与 triage 规则层罐头回复统一消费 onboarding_config(与建线程欢迎行同一份,杜绝两套自我介绍),welcomeText+入口卡带卡落库;零 LLM、rule_greeting 路由键与仲裁留痕口径不变。
- **admin 引导配置编辑面(E)**:PUT /api/tenant/{id} 收 onboardingConfig 完整 JSON——服务端 `validate_onboarding_config` 校验(未知顶层键/按钮错形 400 诚实失败),携带即整体覆写、未携带保留(合并式);GET /api/tenant/list 回读供预填;admin JSON 文本域(非法 JSON 提交前拦截、服务端 400 经 alert 可见)。
- **web 欢迎语服务端权威(F)**:`DEFAULT_ASSISTANT_MESSAGE` 退役——初始/切换/空历史一律空时间线,welcome 行经 loadHistory 从服务端恢复(含入口卡渲染与 send_message 动作分发),前端不再本地伪造。

### ✅ 验证 (Verification,如实)

- engine pytest **329 passed**(新增 38:onboarding 配置 12 + 问候旁路 26),ruff 干净;网关契约套件 **113 passed**(本特性 13 条:threads 列表 4 + 引导生命周期 5 + 租户引导校验 4;评审删 1 条超规格客户端 limit 测试、补 1 条引导失败不阻断测试,总数与 2.6.4 基线 113 持平),web/admin tsc + biome 干净。
- promptfoo 无漂移:统一伞 56 + planner 8 基线不动(全用例无纯问候输入,旁路仅精确命中,无重钉需要)。
- 已知边界(如实记录):web `handleDeleteThread` 调用的 `DELETE /api/chat/threads` 服务端仍不存在(本次地图仅指定 GET,删线程为存量缺口,列入下张地图);存量旧线程(迁移前创建)无 welcome 行,空历史如实呈现空时间线。

---

## [2.6.4] - 2026-09-10 (意图仲裁化:正则建议、LLM 仲裁 —— 留痕/信号源/快轨仲裁员/锚点降级/评测伞)

起点(`/grill-me` 评审):`graph/nodes` 的意图解析是否需要优化。结论:分流瀑布本身高效,病灶在**终局权分配**——非 LLM 层(正则/槽位/锚点)独自把对话判死后无迹可查、无信号可救。四轮评审定下「正则建议、LLM 仲裁」模型,8 张工单(spec:`.scratch/intent-arbitration/`)分两阶段落地:

### ✨ Features (阶段 1:留痕与信号底座)

- **仲裁留痕(01)**:各判定层以 `{layer, intent, confidence}` 快照累积 `proposals`,终局经 `log_intent_to_db` **单点落库** `intent_logs`(`candidates` 列 + `winner` + `arbitration_reason`)——修复槽位层与 skill_fast_track 同输入双写;`llm_call_logs` 补 `node` 归因,每笔 LLM 调用可溯源到图节点(延迟统计/成本归因的地基)。
- **坏例池两个新信号源(02)**:`intent_conflict`(candidates 跨意图族:动作形 × 咨询侧,须来自不同层)与 `intent_mismatch`(LLM 宣称 out_of_scope × 落库 general_query 不符),挂单点落库后入池;信号只入池不直接成为断言,经人工 triage 并入评测语料。
- **评测伞扩展(03)**:统一套件意图分类用例改测**真引擎**(`agent_provider._triage_full`,经 intent_logs 带出仲裁留痕),classify 回声 provider 退役;新增 `intentF1`/`notOosCanned`/`arbitrationTrace`/`ragDirect`/`sameAskConsistency`/`slotClarification` 文件化 scorer(promptfoo 0.111 内联箭头函数断言不执行,必须 file://);伞面 54+8,基线全钉绿。
- **意图注册表合一(04)**:消费方驱动收敛——`AgentIntentType` 枚举为唯一事实源,F1/评测断言/分流路由同源消费。

### ✨ Features (阶段 2:终局权重分配)

- **咨询快轨终局权收编(05)**:直答 prompt 带 ROUTING VETO——用户实为请求执行动作时返回 `__ROUTE_TO_ACTION__` 哨兵,快轨放行 fallthrough 完整管线(正则误命中的代价从「答非所问且关会话」降为多走一次既有管道);Step 3 侧否决降级 general_query 零规划。零新增调用/延迟:p50 咨询路径仍是单次直答,答案生成器升级为生成器+复核员;标记回复严禁写语义缓存。
- **锚点 oos 终局权收编(06)**:Step 2 判定 4(29 锚句余弦 ×0.86 硬阈值)不再独自关会话——记 `embedding(out_of_scope)` 提议后 fallthrough Step 3 精判:确认出范畴照旧收尾(`llm_out_of_scope`,candidates 呈现 embedding→structured_llm 确认链),改判走咨询直答/动作管线。实测靶案例「买个东西怎么买」(oos 锚句相似 1.000 的购买流程咨询)从罐头「超出服务范围」转判 shopping_guide;route key `embedding_out_of_scope` 退役。真 oos +1 确认调用,node 归因单列可见,p50 咨询路径不含此路径。
- **冲突触发仲裁·数据定夺(07)**:01 留痕 393 行直接审计「槽位/锚点判动作 × 咨询形措辞」靶形状 **0 例**(冲突 33 例全为 slot(chat)×动作胜出的良性形状)——显式记录「接受残余,不加 LLM 仲裁调用」决策(硬上会令礼貌措辞的真动作平白 +1 调用);补零调用观测标记 `is_consult_shaped_marker` 挂槽位层动作终局,命中记 `consult_shaped_gate` 提议,残余复现对坏例池信号源可见(此前单层动作终局无 consult 侧候选,残余不可见无从积累数据)。

### ✅ 验证 (Verification,如实)

- engine pytest **291 passed**(阶段 1 基线 276 + 阶段 2 新增 15:锚点仲裁 3 + 冲突标记 12),ruff 干净;网关契约 100 passed。
- 延迟/调用数实测(`llm_call_logs` node 归因):咨询直答缓存未命中 **1 次调用**(直答兼任仲裁员,与 2.6.2 快轨持平)/ 复问 **0 次调用 0.1s**(语义缓存)/ 真 oos **1 次确认调用 5-6.5s**(06 引入,p50 咨询路径不含)/ 动作查询带单号 triage 阶段 **0 次 LLM 调用**(技能快轨)。05 仲裁员否决路径实弹验证(5-token 哨兵 → fallthrough → 动作管道),02 冲突信号同步入池。
- promptfoo 统一伞 54 用例 + planner 伞 8 用例终钉全绿(基线 README 数字同步)。
- 已知残余(如实记录):无标点「谁」系疑问句(「改地址的话转寄运费谁承担的呀」)对快轨闸门与 07 标记同时隐形,槽位层判动作反问单号而知识库有答案——留痕可见、待放量后凭 02 信号复盘,不在本批硬修。

---

## [2.6.3] - 2026-09-09 (破损图 OCR 单号消费 + 消歧闸门意图浮现点补全 + 幽灵单前置拦截)

诊断起点（/diagnosing-bugs）:用户上传破损鞋图（图内印有「破损投诉 ORD-77777」字样）+「坏了」，机器人却回问"是 9081 还是 9082 哪笔订单出了问题"。vision 实弹输出完全正确（`extractedOrderId=ORD-77777` / ocrText / severe 0.95）——错在引擎把识别结果丢掉了，三层缺陷连环：

1. **OCR 单号算完即丢**：`vision_analysis["extractedOrderId"]` 全链零消费，不进 intents.entities / order_context / 槽位 → 引擎"看不到"图内单号 → 回问订单（intent_logs 佐证 entities 恒空）。
2. **消歧闸门时序错位**：2.6.0 的商品归属消歧只挂 Step 1.6（认 SlotExtractor 阶段的 intentType），而「坏了」这类模糊损坏词槽位阶段判 `chat`，售后意图要到 Step 2 判定 3 才由 `damage_assessment` 浮现 → 为本场景造的选择卡对典型措辞**永不触发** → planner 深规划 ~50s 由 finish 自由发挥。
3. **幽灵单直达 HITL（连带发现的存量缺陷）**：OCR 出的或随手敲的单号（ORD-77777 / ORD-99999 三库查无此单）直接开 waiting 审批工单，finish 终稿还谎称"已为您发起退款申请"——文本路径同样中招（实测「帮我退款 ORD-99999」），非本次回归。

### 🐛 Fixes

- **OCR 单号消费（`triage/intent_triage_engine.py`）**：Step 0.5 计算 `vision_order_id`；Step 1.5 同步已确认上下文（TaskMemory.orderContext）进 state（此前已确认单号在轮间丢失）+ OCR 注入后重跑槽位抽取（退款严格抽取器经 `orderContext.targetOrderId` 取到，与消歧 matched 注入同型）。消费优先级 **文本显式 > 已确认上下文 > 图内 OCR**，OCR 永不覆盖已确认单号。Step 2 各判定单号融合 `matched_order_id or confirmed_order_id or vision_order_id`，判定 1/2/3 返回透传 `order_context`。
- **消歧闸门补到全部意图浮现点（同文件）**：Step 2 判定 3（模糊损坏词由 damage_assessment 浮现）与 Step 3（分类器精判浮现）带图缺单号同样过 `disambiguate_product`；Step 3 侧 `vision_disambig_matched` 令注入前的陈旧 `missingSlots` 澄清让位（结构化输出的 missingSlots 是注入前的快照）。两态收口统一走新增 `_vision_disambig_bypass`（无候选明示指引 / 多候选商品选择卡），与 Step 1.6 共用。
- **幽灵单前置拦截（`approvals/gatekeeper.py` + `graph/nodes/step_execution_engine.py`）**：`check_double_refund` 补 `orderFound` 契约（经 `find_order_by_id` 三源按归属查询；查询异常 fail-open，物理分发层兜底）；执行器 4.1.1 在审批门（4.4）**之前**对查无此单诚实失败（"未查询到订单 [X]，或该订单不属于当前账户，请核对订单号"），不开 HITL 工单、不虚构退款进度。技能 fast-track 路径本就有同款校验（`order_skills.py`），执行器在此对齐。

### ✅ 验证 (Verification，如实)

- 新增 `tests/test_vision_order_consumption.py` 5 用例（事故回放：实弹 vision 输出 + 锚向量定向 refund——OCR 单号流入实体/上下文、已确认单号不被 OCR 覆盖、模糊损坏词出选择卡、OCR 有单号跳过消歧、Step 3 浮现同样出选择卡）；`tests/test_double_refund_replay.py` 补幽灵单用例（红→绿：修复前 `status=pending` 开工单，修复后 `failed` 且工单数不变）。engine 全量 **234 passed**（2.6.2 基线 227 + 7），ruff 干净。
- 实弹矩阵（dev 网关 + GLM-4.6V，全部绿）：
  - **OCR 路径**：事故原图（带 ORD-77777 字样）+「坏了」→ OCR 单号被消费 → 幽灵单拦截诚实失败"未查询到订单 [ORD-77777]，或该订单不属于当前账户"，幽灵工单 0 新增；
  - **选择卡路径**：裁掉文字的破损鞋图（OCR 无单号）+「坏了」→ `vision_disambig` 路由（intent_logs 钉死）→ 商品选择卡（9081 冲锋衣 / 9082 工装裤，点选载荷带单号下一轮走 `ORDER_ID_RE` 正则闭环）。
- dev 库 8 张 ORD-77777/ORD-99999 waiting 幽灵工单系修复前实弹测试残留，已清理（现 0 张）。
- 网关契约套件由人工 `bun run test:eval` 复验（本次改动均在 engine 侧，不触网关契约）。
- 文档同步：`.claude/rules/agent-engine.md` §1.3（消歧浮现点 + OCR 消费条目）/ §1.6（幽灵单前置拦截）；`docs/architecture/multimodal-and-rich-cards.md` §2.3（OCR 消费语义落地）/ §6.0（闸门时序表）/ §6.3（幽灵单拦截）；README 商户悬浮窗能力描述。

---

## [2.6.2] - 2026-09-09 (商户聊天分钟级延迟治理:思维链关闭 + planner 封顶 + 咨询类 RAG 直答快轨)

诊断起点:「查询等了好几分钟没有回复」。根因非 db:seed(RAG 空有冷启动自愈),而是 glm-4.7 **默认开 thinking**——每次调用先吐大量 reasoning token(裸测同题 79.9s vs 关闭 7.5-18s),而客服管线一次提问串行 3-4 次调用(triage 分类 → planner 深度规划 → executor → finish 终稿),叠加即 57-114s。政策类问题还有额外病灶:planner 曾对「退货政策」生成 5163 token(73.7s),且咨询类在意图体系里没有独立档位,按措辞随机误落三处(反问订单号 / 误判 refund 动作进深规划 / general_query 两跳)。按用户「按顺序解决」三刀切:

### ✨ Features (新功能)

- **思维链关闭(`llm/chat.py` `_get_request_payload` 单点收口)**:`AI_THINKING=disabled`(默认)时统一经 `extra_body` 注入 `{"thinking":{"type":"disabled"}}`——thinking 非 openai SDK 标准参数,顶层直塞 create() 即炸 `unexpected keyword argument`,必须走 extra_body 通道;`setdefault` 尊重调用方覆写;`enabled` 不注入(换不支持该参数的提供方时规避 400)。finish/executor 等全部聊天调用默认受益,4-10 倍延迟改善。契约由 `tests/test_llm_chat_model.py::TestThinkingDisabled` 钉死。
- **planner 输出封顶(`graph/nodes/planner.py` `planner_llm()` 工厂)**:`bind(max_tokens=AI_PLANNER_MAX_TOKENS)`,默认 2000——封顶防失控,截断 JSON 落 planner 兜底单步计划(降级不炸会话);bind 仍包 `_ResilientChatOpenAI`,熔断/遥测不丢失。契约由 `tests/test_planner_token_cap.py` 钉死。
- **咨询类直答快轨(`triage/consult_fast_path.py`,挂 triage Step 1.4)**:政策/尺码/物流时效等「问知识」型输入单次 LLM 调用直答,旁路 planner/executor/finish 终稿全程(3-4 次串行调用 → 1 次;重复问 → 0 次):
  - `is_consult_query` 咨询形判定:咨询话题 × 疑问语气,三重否定闸(显式订单号 / 动作形与复合意图措辞 / 带图——带图售后走视觉定责管道);≤12 字裸话题(「退货政策」)省略式也算。
  - 编排 `run_consult_direct_answer`:语义缓存先查(≥0.96 秒回,先于 RAG 闸使 FAQ 复放不受知识库空弱影响)→ 复用 run_agent 预取的 RAG 切片(零额外检索,top 相似度 ≥0.55 才直答)→ 单次调用(品牌人设 + 切片 + 近期历史)strictly grounded 直答 → 答案回填语义缓存;熔断穿透,其余失败回落。
  - RAG 空弱/直答失败回落 general_query 零规划旁路(finish 诚实作答),**严防旧误路由**:Step 1.5「退货」字样误判动作形反问订单号、Step 2 判定 3 关键词误判 refund 动作进 planner 深度规划。
  - 意图体系同步补 `consult` 档位:`AgentIntentType.CONSULT` + structured_classifier 类目 10(问知识非办事、永不与订单号共存),分类器判 consult 时走同一快轨。
  - 缓存信任模型:`is_consult_query` 的动作形否定模式即读写两侧防投毒闸,刻意不过 `is_action_query`(「退货政策」会被 OrderRefundSkill 兜底正则嗅探成动作形,对咨询形输入是误报)。

### 🔍 Findings (核查结论,未动代码)

- **商户悬浮窗等待期无 thought 播报(#7)**:widget 仅订阅 Redis pubsub `thread:{id}:message`(终稿回复),引擎 `${jobId}:status` 进度事件走 Redis Streams 网关 SSE,商户侧从未订阅——等待期只有静态 spinner。属产品决策(要不要接进度流),本次未接线。

### ✅ 验证 (Verification,如实)

- 新增 `tests/test_consult_fast_path.py` 33 用例:咨询形判定 11 正例 × 13 反例(动作形/订单号/复合意图/域外全覆盖)、直答编排(RAG 过线单次调用 + 缓存回填/弱相关不发调用/空 RAG/带图守卫/异常回落/熔断穿透/缓存命中 0 调用)、triage 接线(直答命中旁路 output + 空弱回落 general_query 不再误判动作形反问订单号)。
- engine 全量 227 passed(含 #5/#6 套件 7 用例),零回归;ruff 干净;`.env.example` 补 `AI_THINKING` / `AI_PLANNER_MAX_TOKENS` 注释条目;`.claude/rules/agent-engine.md` §1.3/§2 同步。

---

## [2.6.1] - 2026-09-09 (商户 aurora RAG 知识库:docs/knowledge 文档驱动摄取,种子不再写死)

商户门户(极光潮品,businessId `aurora`)此前在 `rag_documents` 无任何切片——商户聊天问退换货/尺码/保养,ContextualRAG 检索恒空,只能靠 LLM 通识硬答。本次补齐知识,且按用户要求**知识不写死在种子里**:文档即数据源,种子与冷启动自愈同源读取 `docs/knowledge/*.md` 切片入库。

### ✨ Features (新功能)

- **知识文档驱动摄取 (`rag/knowledge_files.py`)**:
  - 承接 TS 退役 `updateRag.ts` 的角色,规格对齐 `docs/rag-chunking-and-search.md` §2:frontmatter(title/businessId/category)声明归属租户(缺 businessId 整份跳过,多租户安全——绝不猜测归属);`#`/`##`/`###` 维护章节路径 headerPath;SOP 有序列表原子不拆;超长章节按空行段落贪心打包(≤500 字符);确定性上下文摘要(Anthropic Contextual Retrieval 形态,零 LLM 调用)。
  - `docs/knowledge/aurora_store_and_products.md`:极光潮品门店与商品知识指南(售后退换货 7 天无理由/尺码版型/户外面料压胶护理/顺丰物流/门店会员),内容对齐 `merchant_seed` SPU 域数据与售后时效基准(`get_return_window_days` 无租户覆写默认 7 天),知识与技能行为不打架。
- **种子改为读文件 (`db/seed.py`)**:`_seed_rag_documents` 内联硬编码三元组(2026-09-09 前)退役,改为摄取 `docs/knowledge/` 全部文档(现有 nike/adidas/ecommerce 文档一并纳入,nike=2/adidas=2/ecommerce=2/aurora=5 切片);幂等语义从裸 INSERT(重复 reseed 无限堆行、挤占检索 Top-N)改为按 (business_id, source_url=文件名) 整组替换(TS `replaceKnowledgeFile` 同义),管理端人工新增行不受影响;另一次性清理三条伪 URL 旧行。
- **冷启动自愈同源 (`rag/contextual_rag.py`)**:`_ensure_seed_data` 空表时优先摄取知识文件(与种子同一数据源),文件缺失/不可读回退 TS 基线内联 SEED_DOCS(原行为不动);切片 metadata 带 docTitle/headerPath,检索与 admin RAG 列表可直接展示。

### ✅ 验证 (Verification,如实)

- 新增 `tests/test_merchant_rag_knowledge.py` 6 用例全绿:解析器(frontmatter/SOP 原子/无归属跳过)+ 播种幂等(双跑行数稳定、伪 URL 旧行清理、人工行保留)+ 检索租户隔离(aurora 只召回 aurora,Nike/Adidas/三里屯/淮海路零泄漏)+ 空表冷启动文件摄取;engine 全量 190 passed;ruff 双服务干净。
- 真实 embedding 实弹冒烟(dev 库 `db:seed` 后):「冲锋衣怎么洗」→ 户外面料护理(0.669)、「退换货政策」→ 售后退换货(0.667)、「鞋码怎么选」→ 尺码版型(0.713)、「顺丰多久到」→ 物流配送(0.664),语义路由全部命中正确章节且过 0.4 断路阀;双跑 `db:seed` 后按租户行数稳定(nike=2/adidas=2/ecommerce=2/aurora=5),dev 库幂等实证。已供环境重跑 `bun run db:seed` 即生效;知识目录可经 `RAG_KNOWLEDGE_DIR` 覆写。
- 双轴 code-review(Standards/Spec)收敛修复:种子 DELETE 补租户限定(同名异租户行不得误伤,测试钉死)、chunk→row 组装收敛 `KnowledgeChunk.metadata_dict()`(seed/自愈共用)、知识目录缺失时回退显式播报、`docs/rag-chunking-and-search.md` §5/§6 由退役 TS 脚本 SOP 换为 Python 摄取现实。

---

## [2.6.0] - 2026-09-09 (商户端多模态 + 破损图商品归属消歧:发破损图自动关联订单)

2.5.0 收官后的两个追加交付(grilling 共识→直接实现):商户悬浮客服接入图片链路;破损图不再机械追问订单号——vision 摘要 × 近单商品行 LLM 消歧,高置信自动关联。期间连带挖出并修复 **bigmodel glm-4.7 结构化调用全量 400** 的管线级缺陷。

### ✨ Features (新功能)

- **商户悬浮客服多模态接入 (`83acb98`)**:
  - `FloatingChatWidget` 补齐图片能力:回形针上传(复用 `POST /api/chat/upload`)→ chips 缩略预览(可移除)→ `POST /api/store/chat` 携带 `imageUrls` → 气泡上方缩略图渲染 + 点击放大遮罩;空文本有图以兜底文案发送;历史接口 `imageUrls` 三处映射还原(localStorage 缓存随消息对象整体序列化,自动兼容)。
  - **网关 `store_chat` 补写用户行(治 005 回归)**:web 的 `dispatch_chat` 落库用户行而 merchant 的 `store_chat` 从未落库——005 治理把引擎侧用户行写入拔除后,商户用户消息完全不落库、历史恢复缺用户行;对齐 dispatch 语义(读 `imageUrls`/透传 `AgentJobInput`/显式落库),契约两用例入册(带图持久化还原 + 空文本无图 400)。
- **破损图商品归属消歧 (`aed3238`)**:
  - triage Step 1.6(`triage/product_disambiguator.py`):售后意图带图但缺订单号(图内 OCR 亦无单号)时,vision 视觉摘要 × 近单商品行交 LLM 消歧,替代机械"请提供订单号"。三态:**matched**(置信度 ≥0.8 且命中项原样在候选集内,防幻觉键集校验)注入 `targetOrderId` + SSE 播报 + 重跑槽位抽取(本轮直接带上 orderId,免二次澄清);**ambiguous**(多候选/低置信/模型失败)出商品选择 `quick_replies` 卡,点选文本带单号下一轮走 `ORDER_ID_RE` 正则闭环;**no_orders** 明示指引。消歧失败绝不炸会话。

### 🐛 Bug Fixes (缺陷修复)

- **消歧候选源查错库 (`ba05718`)**:候选池原直查 engine 本地表 `get_user_orders_detailed`——商户用户真单在 `agent_merchant.merchant_orders`,engine 表无单,**永远空候选**,消歧三态里的 matched/ambiguous 对商户用户从未成立(冒烟实证 no_orders 假象)。修复:`OrderDomainService.get_recent_product_lines` 门面,商户真单优先(先截断再拉商品行)、engine 本地表兜底,两库优先级与订单列表同源(2026-09-05 同源裁决的延伸)。
- **bigmodel glm-4.7 结构化调用全量 400 (`1b15979`)**:langchain-openai 1.6.0 的 `with_structured_output(function_calling)` 固定发送三个 OpenAI 专有参数,glm-4.7 全部拒收(HTTP 400 code 1210)——`parallel_tool_calls`(任意组合)、`stream:false` 与 tools 同现、`tool_choice` 对象形式;glm-4.6v 均收,vision 通路因此幸免。后果:triage 意图分类器、商品消歧等全部结构化调用失败,**被关键词兜底静默掩盖**(会话看似正常,意图判定长期降级)。修复:`_ResilientChatOpenAI._get_request_payload` 单点收口(invoke/ainvoke/stream 全路径)——剥前两者、`tool_choice` 对象**改写**为 `"required"`(不能剥除:实测去掉后模型遇闲聊 prompt 不调工具,结构化解析即失败;`"required"` 强制语义等价且 bigmodel 收)。诊断链:echo 服务器抓真实请求体 + curl 参数矩阵逐项二分。

### 📝 Docs (文档同步)

- `docs/architecture/multimodal-and-rich-cards.md`:总览图补 merchant 入口与消歧挂点;§5.1 写入方三入口;新增 §5.2 商户多模态接入、§6 消歧三态与候选池门面、§7 bigmodel 参数兼容矩阵。
- `.claude/rules/agent-engine.md`:§1.3 补消歧条目、§1.4 消息写所有权补 store 入口、§2 规则 2 补 bigmodel 参数兼容事实。
- `.wayfinder/multimodal-image-chat/map.md`:商户端图片输入从"Not yet specified"移入收官后追加;"消歧并入用户文本 prompt"立为新的观察项。
- `README.md` 商户悬浮窗特性清单补多模态图片上传。

### ✅ 验证 (Verification,如实)

- engine 三套件 36/36 全绿(消歧 13 + payload 卫生 2 + 韧性 21);gateway 契约 100/100(含 store_chat 带图两用例);ruff 双服务干净。
- 真实 bigmodel 实弹:`with_structured_output` 返回 `ok=True`(修复前 1210)。
- 端到端冒烟(上传真图 → store/chat):选择卡候选已来自商户真单(9081 冲锋衣/9082 工装裤)——候选源修复实锤;matched 分支真实 LLM 判 0.85 自动关联 9082 工装裤;端到端走 ambiguous 系 glm-4.6v 诚实判定(测试图为牛仔裤,与候选确实不符),非 bug。
- promptfoo 基线未复跑:triage 分类器此前一直走关键词兜底,结构化判定恢复后 Classify 分册判定理论上有变化空间,建议下次 `bun run test:prompt:compare` 复验后视漂移重钉。

---

## [2.5.0] - 2026-09-09 (多模态图片客服:上传→看图定责→卡片回复→刷新还原全链贯通)

wayfinder 执行图 `multimodal-image-chat` 收官(001-005 五票):回收 TS 退役时留下的四个断点——上传端点 404、triage 视觉 TODO、messages 无图列、历史不还原图。用户在 web 聊天发物流面单/破损商品图,平台真实"看图办事"。

### ✨ Features (新功能)

- **图片上传端点 `POST /api/chat/upload` (`52d87ed`+`ae64ac6`,wayfinder 002)**:
  - MIME 白名单(jpeg/png/webp/gif)、流式读取实测 10MB 上限(超限删半成品返 413)、UUID 文件名落盘 `public/uploads`(path-traversal 免疫)、StaticFiles `/api/uploads` 回读;契约三用例入册,契约路由 41→42 三处文档同步;新增 `python-multipart` 依赖。
- **engine 视觉模块 `vision/analyzer.py` (`7c31510`+`2047521`,wayfinder 003)**:
  - 移植 TS visionAnalyzerService(考古基准 f71f7fa / b75fb78^)并修三大 TS 缺陷:①手写 ```json 围栏剥离 → `with_structured_output(method="function_calling")`(GLM-4.6V 无 response_format);②1500ms 硬超时 → `AI_VISION_TIMEOUT_SECONDS` 可配(默认 15s);③本地图 `/api/uploads/` 引用 → base64 Data URL 直传(bigmodel 拉不到 localhost)。
  - 挂 triage Step 0.5(📷 状态播报 + try/except 保险带,视觉失败绝不炸分流);OCR 单号正则(ORD-/SF/YTO/ZTO/EMS/TRACK)、破损三级定责(negligible/minor/severe)、LLM 失败降级启发式(confidence 0.88)、PII 脱敏复用 scrubber;`get_vision_model()` 入 `llm/chat.py` 统一入口(`AI_VISION_MODEL` 默认 glm-4.6v,刻意不入韧性层——视觉失败域独立)。
- **图片持久化与会话还原 (`8647697`,wayfinder 004)**:
  - Alembic 0006 增列 `messages.image_urls`(JSONB 引用,inspection 幂等守卫,只存 URL 不存 blob);gateway `append_message` 透传落库、dispatch 用户消息带图入库(此前 AgentJobInput 带图但落库丢弃)、`get_conversation_timeline` 带出 camelCase `imageUrls`(web 聊天历史与 admin 会话时间线共用);前端零改动(002 已备 `Message.imageUrls` 与缩略图渲染),发图→刷新→图与对话俱在。
- **入图归一化与限额治理(wayfinder 005)**:
  - `normalize_image_urls` 收口(剔非字符串/空白、去重保序、**≤3 图/条**截断),挂 `run_agent` 初始状态构建;与网关单张 10MB 限额对齐;垃圾输入只少看图不抛错。E2E 夹具 + `chat-multimodal-damage.e2e.ts`(选图上传→破损图→damage_assessment 卡→刷新还原,chromium)。
  - E2E 实测三修:①`AI_VISION_TIMEOUT_SECONDS` 默认 15s→30s(GLM-4.6V 真实请求可超 15s,超时即降级启发式丢定责);②启发式破损词表补 `断裂|开胶|脱胶`(「鞋底开胶断裂」原全不命中,降级后连兜底定责都丢);③`_uploads_dir()` 默认路径 `parents[4]`→`parents[5]`(原解析到不存在的 `services/public/uploads`,本地图全被跳过)。
- **用户消息单次落库治理(wayfinder 005)**:
  - 双插考古:网关 dispatch/SPI 持久化用户消息(带 imageUrls),`run_agent` 又沿 TS 基线 `shortMemory.addMessage` 盲插无图副本——TS 树里 `appendMessage` 并不存在,网关侧插入系 Python 移植新增,叠加后每条消息时间线 user×2(一行带图一行不带)。裁决:**用户行唯一写入方归网关**(imageUrls 只在入口可得),引擎三处(run_agent 主链/问候旁路/Temporal activity)拔除,assistant 行仍归引擎;`test_user_message_single_write.py` 两用例钉死所有权边界。

### 📝 Docs (文档同步)

- `docs/architecture/multimodal-and-rich-cards.md` TS 残留引用清账(源码路径、1500ms 超时叙述、上传路由位置全部对齐 Python 实况);`.claude/rules/agent-engine.md` §1.3 补入图治理条目;`.env.example` 补 `AI_VISION_MODEL`/`AI_VISION_TIMEOUT_SECONDS`。
- 评测裁决:`eval/testCases/ecommerce/multimodal-damage.json` 维持 `[image: ...]` 文本模拟基线不升级——promptfoo 供给方是文本 LLM 无图片输入位,真实图片链路已由 vision 单测 + E2E 覆盖;基线零改动零重钉。

### ✅ 验证 (Verification,如实)

- engine 169(vision 治理 +3、用户单写 +2)全绿;gateway 97(含图片持久化契约 +2)全绿;ruff 双服务干净。
- E2E chromium:选图上传→真实 GLM-4.6V 定责(severe / 0.95 /「鞋底开胶断裂，完全不能穿」)→damage_assessment 卡渲染→刷新 `?threadId=` 自愈还原图与卡,全链绿;健康链路端到端 ~26s。期间实证:上游 bigmodel 深度限流时链路可拖至 16 分钟(隔夜自愈),vision 超时降级启发式(0.88)仍出卡——双通道容灾按设计工作。
- 已知存量缺口(非本图引入,记录不修):侧栏历史列表依赖 `GET /api/chat/threads`,网关仅实现 POST/DELETE 返 405,刷新后列表恒空(当前线程靠 URL 自愈恢复)。
- `test:prompt:compare` 未跑:文本路径 prompt 零改动(vision 仅带图分支触发,归一化只影响入图数量),基线不可能漂移。

---

## [2.4.1] - 2026-09-07 (「查询热门商品」类措辞空转道歉修复:快轨补词 + 执行器白名单扩容)

### 🐛 Bug Fixes (缺陷修复)

- **「查询热门商品/爆款」类措辞空转 5 分钟后道歉降级 (`852e06c`)**:
  - 事故形态:用户说「查询热门商品」→ 不命中任何意图规则 → LLM 精判 → planner → executor,而 executor 的 `allowed_tools` 白名单继承 TS 基线仅含订单/退款 7 工具,商品工具与快轨伪名 `cart_manage`/`shopping_guide` 全被分发门槛拦截,子任务空转 "without needing tools" 直至 finish 道歉降级(实测一轮 5 分钟)。
  - 修复(四件):
    - `slot_extractor` SHOPPING_GUIDE 规则补入 热门/爆款/热销/热卖/畅销/上新/新品——该类措辞于 Triage 快轨直达 `ShoppingGuideSkill`(实测决策链 35ms、零 LLM 调用);
    - `guide_skills._FALLBACK_RE` 同源补词,动作形嗅探(`is_action_query`)据此拒绝热门类输入命中语义回复缓存;
    - `executor_fast_path` 快轨返回伪名改为 SkillsRegistry 真实技能 id(`skill_cart_manage`/`skill_shopping_guide`)——伪名既不在白名单也查不到注册表,自 TS 移植以来即为永不触发的死路;子串匹配同步修正(裸 `hot` 会误中 what/shot,改用完整词 popular/trending/best seller);
    - `step_execution_engine` base_tools 白名单纳入导购/购物车技能与只读商品工具(`searchProducts`/`compareProducts`/`queryProductSkus`/`queryProductReviews`/`queryProductRanking`/`getCartSummary`),LLM 兜底选择器补第 9 条商品工具指引。
  - **安全边界保持**:写操作购物车工具(`addToCart`/`updateCartItem`)仍不入白名单——加购/改量必须走技能 SOP 管道,不允许 LLM 兜底直调。

### 📝 Docs (文档同步)

- **新增 Git 提交规范 (`01513ef`,CLAUDE.md §6)**:提交作者固定 `weizheng1992`(仓库局部 git config 已覆盖,推送走 SSH key);提交信息只写说明本身,不加 `Co-Authored-By` / `Generated with` 之类的尾注或署名。

### ✅ 验证 (Verification,如实)

- ruff 双服务 clean;功能实测记录(提交时):快轨决策链 35ms、零 LLM 调用;修复前空转 5 分钟道歉路径已复现确认。
- promptfoo 基线未随本提交复跑——SHOPPING_GUIDE 规则扩词理论上可影响 Classify 分册判定,建议下次 `bun run test:prompt:compare` 复验。

---

## [2.4.0] - 2026-09-07 (wayfinder「单实例真实可运营」收官:mock/假兜底全量换成真能力)

六张执行票全部关闭(见 `.wayfinder/single-instance-production/`),平台在单实例部署下真实可运营:真实登录、真实限流、真实熔断、评测真实入库、熔断信号真实入池。

### 🚀 Features (功能演进)

- **auth/login 真实化 (`31e844d`,票 001)**:bcrypt 凭证校验 + JWT 会话(30 天无刷新)+ Redis jti 登出黑名单;新增 `GET /api/auth/me` 静默重校验(用户 UUID 漂移自愈);前端 localStorage 假兜底删除,E2E 切真实凭证。其余用户 `password_hash = NULL` 安全缺省,仅种子账号可登录(admin 侧发券/改密入口为地图遗留 fog)。
- **租户+IP 双维 Redis 滑动窗口限流 (`8742b55`,票 002)**:`RateLimitMiddleware`(ZSET 滑动窗口 + 多键 all-or-nothing Lua 原子扣减)挂 `/api/chat` 与 `/api/v1/spi` 高频入口;XFF 仅可信反代采信最右跳;admin `all` 视图跳租户桶只按 IP 计;Redis 故障 fail-open 不阻断业务。
- **LLM 熔断/指数退避/超时三件套 (`36ded04`,票 003,TS 1:1 移植)**:全局 CircuitBreaker 单例 + 3 次指数退避 + `wait_for` 超时,挂 `_ResilientChatOpenAI` 公共 `invoke/ainvoke` 全覆盖(构造期 callbacks 不穿透 `with_structured_output` 的坑已绕开);熔断中断的会话 job 级降级道歉并落 `resolution_status='llm_circuit_breaker'`;4 节点兜底前置熔断豁免上抛。阈值经 `LLM_CIRCUIT_*` / `LLM_RETRY_*` / `LLM_TIMEOUT_SECONDS` env 可调。
- **promptfoo 评测真实结果入库 (`d66a86f`,票 005)**:结果经 `engine_py.evals.promptfoo_import` 单事务写 `eval_runs`/`eval_results` 三表(`bun run test:prompt:record` 三套件链式自动入库 + `evals:import` 独立通道);`POST /api/evals/run` 返回 410 指引真实通道,随机评测生成器退役为契约测试 fixture,`isMock` 全链路消失;admin `/api/evals/results` 与 `/api/logs` 只消费真值,无数据处返回真实 0。CLI `__main__` 守卫缺失曾致零入库,已补测钉死。
- **熔断信号入坏例候选池 (`844302d`,票 006)**:`run_agent` 会话收口处两路熔断(上游 LLM 级 + 图级转移≥10/工具错误≥3)入池,先验 `suspected_defect`;`record_badcase_signal` 增 opt-in dedupe 幂等护栏;摘要按 source 分组自动收纳。

### 🐛 Bug Fixes (缺陷修复)

- **HITL 挂起计划不落库竞态(`584b1f8`,票 004 E2E 钉出)**:审批工单创建后前端 2s 轮询立即可见,而挂起计划要等运行收口才 `save_task_state` —— 核签窗口内 `job_resume_*` 读到空计划,triage 误判查单,退款永不执行。修复:挂起即落库 + 空 thread_id 拒写 TaskMemory("") 共享键。
- **`POST /api/chat/threads` 契约缺失(`cc7a5d4`,票 004)**:TS 基线服务端从未实现,web「开启新一轮对话」fetch 404 被静默吞掉,按钮长期失效。补齐幂等建线程路由;归属守卫:同 id 异租户/异用户重放 409 不回显他人元数据,无主线程自愈认领。**契约路由 39 → 41**(另含票 001 的 `/api/auth/me`;新增路由均同批补 pytest 契约钉死,冻结 carve-out 见地图 Notes)。
- **tz-aware 送达日期炸退款 + 三方镜像表裸 except 连坐(`584b1f8`,票 004)**:`estimated_delivery` 为 text 列,`NOW()` 写入带时区偏移直接炸日期解析;镜像表更新失败但事务已中止,主退款 UPDATE 的 commit 静默失效、工具照报成功。修复:tz 归一 + 退款/改址/商品补全三处 `begin_nested` SAVEPOINT 隔离 + 显式中文日志。
- **种子 `rag_documents` 绑定参数 `:m::jsonb` 语法炸库(`41fe4ca`)**:改 `CAST(:m AS jsonb)`。

### 🧪 E2E 基建 (票 004)

- 新增 `chat-approval-flow.e2e.ts`(超阈值退款挂起 → 审批卡 → 核签 → 真实物理退款 → 会话落定)与 `circuit-breaker.e2e.ts`(独立 `playwright.breaker.config.ts`,死 LLM 注入 + 阈值 1)。**熔断 spec 关键发现**:问候/订单/退款输入全走 triage 确定性旁路零 LLM 调用,熔断永不触发——须价保咨询类输入必达 Step 3 精判。
- `e2e/globalSetup.ts` 幂等就绪(docker:up → db:push → db:seed,种子 DO UPDATE 重置可重复执行);webServer 显式数组化(gateway 4000 / web 3000 / admin 3001 / merchant 3005);`testIgnore` 围栏(breaker 独占运行 + `.claude/worktrees` 幽灵 spec);admin 陈旧 spec 全量修缮(Combobox 按 cmdk `role="option"` 交互、`getByRole('link')` 防同名撞车);webkit/firefox 浏览器二进制补装。

### ✅ 验证 (Verification,如实)

- gateway 契约 **91 passed**(密封 testcontainers);engine 回放 **5 passed**(含挂起落库回归);HITL/熔断两 E2E spec 单独绿(19.7s / 18.7s);ruff 双服务 clean、biome e2e clean。
- **全量 `playwright test` 未收口**:修复已知根因后 25 passed / 18 failed —— 14 个 firefox 二进制缺失(已补装)、4 个 admin spec 选择器缺陷(已修,基于组件源码静态核对),均待下次全量跑复验。`test:prompt:compare` 未跑(engine 改动仅 HITL 挂起路径,不触 Classify/Planner 提示词)。

### ⚠️ Notes (注意事项)

- 运行中的 dev 网关需重启 `dev:server` 方可生效(uvicorn reload 不监视 engine-py)。
- E2E 全量套件的既有用例回归待一次完整复跑收口(本环境按指示停止测试)。
- 仅种子账号(`test@example.com` / `agent-all-dev`)可登录;真实运营的 admin 侧改密/发券入口未做(地图 fog 记录,立票另议)。

---

## [2.3.7] - 2026-09-05 (双退款事故三层旁路封死 + SPI 技能链路线程上下文透传)

### 🐛 Bug Fixes (缺陷修复)

- **未指明订单号的退款申请静默重退历史已退款订单 (`b355170`,三层修复)**:
  - 事故(2026-09-05 19:08,线程 `merchant_thread_CUST-8801_aurora_*`):用户「我想申请退款」想退 9081,系统把旧回合(04:16)已退款的 9082 物理重退,且全程未发新审批工单。
  - 根因链(DB 证据钉死):线程无已存任务状态 → 槽位提取器全历史反向扫描(含 assistant 消息)回填 9082 → missingSlots=[] 不澄清 → planner fast-path 零 LLM 单步计划 → `check_double_refund` 只查 engine orders 表(商户真单在 `agent_merchant` 库,全盲)→ 线程扫描复用 03:07 旧 `approved` 工单绕过 HITL → `process_refund` 无 REFUNDED 幂等校验 → 商户真单物理重退。
  - 修复(三层防线,自上游到底线):③ 资金类意图(order_return/refund)订单号禁历史回填——只认当前输入与用户已确认 orderContext,缺失强制追问澄清(`slot_extractor` 严格提取 + planner fast-path 降级门 + 深度规划 prompt 例外指令);② HITL 旁路封死——线程扫描只认领 `waiting` 工单,`approved` 等终态只能经 existingApprovalId(审批恢复路径)复用;① 幂等底线——`process_refund` 对任何来源(engine/merchant/third_party)已 REFUNDED 订单拒绝物理重退,`check_double_refund` 改三源判定并按用户归属匹配。
  - 回归:`test_double_refund_replay.py` 3 例红灯转绿(密封 testcontainers PG + 商户镜像表回放事故执行链:重退物理指纹守卫 / 陈旧 approved 工单必须重开 waiting 票 / 缺单号必须澄清)。
- **SPI 技能链路丢弃线程上下文,商户真单被 third_party 过期数据遮蔽 (`25aea43`)**:
  - 根因:triage Skill Fast-Track 与执行器技能派发都把 threadId/userId 传入 `skill.execute(context)`,但 `OrderRefundSkill` 调 `LocalDbSpiAdapter` 时丢弃——`get_order_detail` 硬编码 user_id=None 跳过商户真单回退(`find_order_by_id` 按 user_id 严格归属匹配),拿到 third_party 过期种子状态(事故后 11:09 回复展示错误订单状态即此因);`execute_order_action` 硬编码 thread_id=None,使归属校验(IDOR)、REFUNDED 幂等守卫(2.3.7 上一条新增)、商户写穿透在技能链路全部失效——退款只假写 third_party/engine 表,商户真单纹丝不动。附带发现:adapter success 计算误读 `refundedAmount`(`process_refund` 返回键为 `refundAmount`),物理退款成功却向技能上报失败。
  - 修复:`OrderRefundSkill` / `OrderAddressModificationSkill` 把 context 中的 userId+threadId 透传进 `get_order_detail` 与 `execute_order_action`;adapter 侧 `process_refund` / `change_shipping_address` 改收 `req.threadId`,success/refundedAmount 键名对齐。
  - 回归:`test_spi_client_thread_context.py` 3 例红灯转绿(带身份详情必须读商户真单 / 已退款单经技能链路不再发生任何物理退款写,含 third_party 双侧指纹断言 / 合法退款必须写穿商户真单)。其中"盲退"断言曾因键名错配假绿(物理退款发生但恰好上报失败),补 third_party 物理指纹断言后真红——双断言必要性的一手案例。

### ✅ 验证 (Verification)

- engine-py 65 passed(62 存量 + 6 新增,含双退款回放与 SPI 上下文)/ gateway 契约 69 passed / ruff clean / 无 DEBUG 残留。

### ⚠️ Notes (注意事项)

- 运行中的 dev 网关需重启 `dev:server` 方可生效(uvicorn reload 不监视 engine-py,见 docs/deployment.md 踩坑清单)。
- 退款意图的订单号现强制"当前输入或已确认 orderContext"——多单用户说「我要退款」会收到追问,属预期行为变化(此前静默回填历史订单正是事故根因)。

---

## [2.3.6] - 2026-09-05 (启动与部署指南:dev Temporal 流程与线上部署 runbook 成文)

### 📝 Docs (文档同步)

- **新增 `docs/deployment.md`**:dev 启动流程(基础设施/启动顺序/四种踩坑:dev:all 无 worker、engine 改动不热重载、uv workspace 精确 sync 互剥依赖、7239 端口映射)与线上部署 runbook(部署形态矩阵、Temporal 三路线[暂不部署/Cloud/自托管]、发布步骤、就绪验收、env 矩阵、排障入口)。
- **澄清拓扑真相**:Python 网关从不向 Temporal 提交工作流(全仓无 `start_workflow` 调用方,请求路径为网关进程内 `run_agent` 直跑);worker 的现实角色是 scheduler 载体 + 休眠的 workflow 注册。README §6 服务表"Temporal 离线时本地仿真回退"的 TS 时代表述已修正,并补 §3 未来启用 Temporal 编排的演进步骤(submitter、幂等续跑、SSE 桥接、Schedule 迁移)。CLAUDE.md §5 挂载索引。

---

## [2.3.5] - 2026-09-05 (多实例部署指南:单实例假设盘点与迁移方案成文)

### 📝 Docs (文档同步)

- **新增 `docs/architecture/multi-instance-deployment.md`**:兑现不变量 #3 挂账的"多实例部署前需分布式锁或迁移 Temporal Schedule"。盘点存量组件就绪度(SSE 裸 XREAD 天然安全、outbox SKIP LOCKED 行级安全、审批 Redis SETNX 跨实例互斥、embedding 串行护栏按进程设计无需改、Temporal worker 原生扩容),钉死两个硬缺口:① scheduler 单实例假设(三方案:环境变量止损 → Temporal Schedule 目标态);② socket.io 房间为进程内存态,须加 `AsyncRedisManager` 跨实例广播,否则人工接管双端失联。附扩容前置清单(Redis 升硬依赖、PG 连接池预算、uvicorn 单 worker 假设)与多实例开发约定(新周期任务幂等、进程内存态仅限降级)。CLAUDE.md §5 挂载索引。

---

## [2.3.4] - 2026-09-05 (worker 兼容 temporalio 新 API;本地 embedding 并发推理段错误串行化护栏)

### 🐛 Bug Fixes (缺陷修复)

- **`bun run worker` 启动即退 (`engine_py/temporal/worker.py`)**:
  - 症状:报"temporalio 未安装"误导信息,实为 `ImportError: cannot import name 'Connection'`——`uv sync --extra worker` 解析到 temporalio 1.32.0,该版本把 `Connection` 并入 `Client`(classmethod `connect`),Worker 首参即 `Client`。
  - 修复:改用 `Client.connect(address)`;验证:worker 正常启动,Temporal Server 离线时按设计退化为纯周期任务进程。
- **本地 embedding 并发推理段错误 (`engine_py/llm/chat.py`)**:
  - 症状:两个线程同时经本地 torch embedding(sentence-transformers)encode → 进程级 SIGSEGV(exit 139)。触发面极广:网关任意两个并发聊天请求的 triage 向量化、审批恢复与新聊天同跑、worker 一轮对账派发多条事件;进程连同全部 SSE 连接一起死。最小复现:`asyncio.gather` 两个 `aembed_query` 即崩(与 temporalio 无关,单独加载模型正常)。
  - 修复:`get_embedding_model()` 本地分支包 `_SerializedEmbeddings`——进程内 `asyncio.Lock` 串行化 `aembed_query/aembed_documents`(openai 提供方为网络客户端不经包装;同步方法透传)。锁可在线程中构造(预热线程)、loop 中使用,3.14 验证通过。
  - 回归:engine 侧新增 `test_embedding_concurrency.py`(3 并发 aembed 钉死;修复前 pytest 进程直接被 SIGSEGV 杀死),套件 33/33 绿。

### ✅ 验证 (Verification)

- **发件箱对账兜底实跑验证**(2.3.3 修复的补偿路径):启动 worker 后,scheduler 首轮扫描即捞出 2 条滞留事件(processedCount=2, dispatchedCount=2);重派发经真实 run_agent 执行后双双落 `completed`(retry 2 = 一次段错误尝试 + 一次兜底成功),商户订单幂等无损。修复前滞留的 2 条事件(含用户原始工单)已全部闭环。

### ⚠️ Notes (注意事项)

- engine 侧新增用例已实跑全绿(33/33);gateway 契约套件无涉改,按约定仍由人工 `bun run test:eval`。
- dev 环境如需对账兜底常驻,单独跑 `bun run worker`(scheduler 随其启动);`dev:all` 不含 worker。

---

## [2.3.3] - 2026-09-05 (商户退款审批通过后店铺无变化:HITL 恢复派发链路断裂修复)

### 🐛 Bug Fixes (缺陷修复)

- **审批通过后退款不执行、店铺订单无变化 (`engine_py/approvals/gatekeeper.py`)**:
  - 症状:商户门店聊天申请退款 → admin 审批通过(接口返回 success)→ 商户库 `merchant_orders` 状态永不翻转,顾客与店铺侧均"没反应"。
  - 根因(用户复现工单 + 发件箱错误信息直接钉死):工单创建路径(`evaluate_pending_approval_state` / `create_pending_approval_ticket`)不写 `pending_approvals.business_id`(NULL);审批 Fast-Path 把 `record.business_id`(None)显式传入 `AgentJobInput(businessId=...)`,**显式 None 绕过 pydantic 默认值**直接校验崩溃 → resume 任务永不派发,事件滞留 `approval_outbox_events.status='pending'`(error: `AgentJobInput businessId Input should be a valid string, input_value=None`)。对账 Worker 本可 10s 后兜底重放(payload 侧有 `or "ecommerce"` 回退),但其随 Temporal worker 入口启动,`dev:all` 不含 worker → 兜底也不在场,链路彻底断裂。
  - 修复:① 新增 `_thread_owner_context` 助手(threads 表事实源),两个工单创建点落库 `business_id`;② 派发点 `process_approval_action` 以 `record.business_id → 线程归属租户 → "ecommerce"` 三级回退构造派发载荷与 `AgentJobInput`(存量 NULL 旧工单同样可恢复);③ outbox payload 同步携带真实租户。
  - 回归:gateway 契约新增 `TestApprovalResumeDispatch`(走执行器真实创建分支 → 断言工单落租户、Fast-Path 派发后 outbox `completed` 且载荷携带真实租户;修复前断言 `pending`+校验错误)。旧用例 `test_resolve_fixture_approval` 之所以从未拦住:fixture 直插 SQL 自带 business_id,绕过了出问题的创建分支,且断言只看 HTTP success——派发崩溃恰好也返回 success。反馈回路脚本 `scripts/debug/refund-approval-e2e.sh` 保留(红→绿实测:审批后 3s `PAID→REFUNDED`)。

### ⚠️ Notes (注意事项)

- 新增 pytest 用例按仓库约定由人工触发 `bun run test:eval` 验证。
- 开发环境若依赖发件箱对账兜底,需单独启动 `bun run worker`(scheduler 随其启动);仅跑 `dev:all` 时兜底不在场,Fast-Path 是唯一派发路径——本次修复后 Fast-Path 已可靠。
- 修复前创建的存量工单 `business_id` 仍为 NULL(派发点回退已兼容,无需数据迁移);历史"已批准未执行"的订单可由顾客重新发起退款走新链路。

---

## [2.3.2] - 2026-09-05 (商户聊天查单与订单列表双库统一、租户注册门禁、语义缓存防投毒双闸门、admin 十大模块全面接真实后端)

### 🐛 Bug Fixes (缺陷修复)

- **商户聊天查单与订单列表展示不一致 (`engine_py/tools_registry/order_domain.py` + `gateway-py/merchant_domain.py`)**:
  - 根因:订单数据三个物理存储物理隔离——商城下单只写 `agent_merchant.merchant_orders`(列表页数据源),而聊天 `listUserOrders` 只读 engine 本地 `agent_platform.orders`;后者空结果时还会**自愈播种 2 笔虚构演示订单**(¥199/¥89),且两侧查询均带 `OR user_id='CUST-8801'` 跨用户回退,任何用户都会混入演示用户订单 → 两视图永久发散。
  - 修复:order_domain 新增 `_merchant_reader_engine`(URL 推导对齐 gateway `merchant_db`,lru_cache 单例)直读商户库,聊天列表商户真单优先、严格 `customer_id` 归属、绝不播种;按单号查询 engine → merchant → third_party 三级回退(全链严格归属);退款/改地址**写穿透**商户库(聊天侧退款后 `merchant_orders.status` 真实翻转);商户库不可达时优雅降级 engine 本地表。列表页 `/api/store/orders` 同步移除 OR CUST-8801。
  - 回归:engine 侧 4 用例(商户源优先/空不播种/兜底 SQL 严格归属/按号查询回退+防跨用户泄漏)+ gateway 契约 `TestStoreOrdersStrictScoping` 2 例;反馈回路脚本 `scripts/debug/order-view-diff.sh` 保留(三演示用户全 GREEN)。
- **admin 会话列表恒空 (`apps/admin/conversations`)**:`/api/conversations` 契约返回 `{conversations, total}`,页面却判断 `res.items` —— 字段名错配使真实数据永远走不进渲染分支,此前被假数据掩盖,清空假数据后暴露。

### 🔐 安全加固 (Security Hardening)

- **商户路径租户注册门禁 A 档 (`gateway-py/routers/merchant.py`)**:商户服务路径从不咨询 tenants 注册表,自报 `businessId`(如 ghost-tenant-999)即可获全套引擎服务并收到品牌扮演回复。新增 `check_tenant_registered`:tenants 表须存在且 `status='active'` 否则 403;注册表不可用 503(fail-closed);"all" 聚合视图放行。覆盖 `/api/store/chat`、`/api/store/chat/messages`、`/api/admin/conversations{,/{id}}`、`/api/admin/approvals` 五个客户端可传租户身份的入口。
- **补遗失的 CORS 中间件 (`gateway-py/main.py`)**:TS 基线 AppModule 有、Python 移植遗失。此前 admin(3001) 直连 4000 被浏览器预检拦截,`/tenants` 页静默回退前端硬编码假租户,掩盖真实注册行。
- **语义缓存防投毒双闸门 (`engine-py/skills/` + `graph/nodes/finish.py` + `triage/`)**:幻觉"已成功 XX"回复会无条件回填语义缓存,相似请求以 ≥0.96 相似度永久命中、绕过真实技能执行。新增 `is_action_query()` 动作嗅探(任一技能 `can_handle` 即动作形,嗅探失败按动作处理——宁可缓存失效,不可放行投毒):动作形输入**禁写**(finish 无工具背书的终稿不得回填)且**禁读**(triage 不查缓存,必须落真实执行管道)。12 用例钉死双闸门。

### 🧹 数据真实性清理 (Data Truthfulness)

- **admin 十大模块全面接真实后端 (`apps/admin` + `gateway-py`)**,三连修:
  - 清空 10 页(tenants/skills-tools/conversations/audits/rag-studio/evals/guardrails/personas/billing/system-logs)`INITIAL_*` 硬编码演示数据与 fetch 兜底假数据;`useAdminCrud` localStorage 持久化仅限本地模式;网关 `/api/tenant/list` 移除硬编码演示租户兜底(空表返回空列表)。
  - 租户筛选器改为 `loadTenantsFromServer()` 从真实注册表动态加载(仅 active),移除最后一处硬编码演示租户。
  - tenants 不可编辑修复:网关新增 `PUT /api/tenant/{id}`(tenant_configs 合并式覆写 + jsonb 显式 CAST);`api.ts` 对齐冻结契约(ragApi.search→`POST /api/rag/query`、billing 配额→`PUT`、补 tenants.update / guardrails.create / delete);移除 skills-tools 与 rag-studio 的假创建/假编辑;billing/evals 统计卡改真实接口汇总。浏览器实弹验证 10 页全过。

### ⚠️ Notes (注意事项)

- 本批次 pytest 契约套件新增用例(`TestMerchantTenantGate` 5 例、`TestStoreOrdersStrictScoping` 2 例、语义缓存 12 例)按仓库约定由人工触发 `bun run test:eval` 验证;engine 侧单测已实跑全绿(32/32)。
- 订单三库约定:商户租户订单读写必须经 order_domain 的 merchant reader,不要往 engine orders 表加同步副本;聊天退款已写穿透商户库,但**改地址仅更新 shipping_address 快照**,不触发商户侧物流系统。

---

## [2.3.1] - 2026-09-04 (契约测试套件首次全绿:SSE 静默断流、审批恢复跨租户搬家、商户中继延迟三大生产缺陷修复)

### 🐛 Bug Fixes (缺陷修复)

- **SSE 流空闲 5 秒必静默断流 (`engine_py/event_bus.py` + `gateway-py/routers/chat.py`)**:
  - 根因:redis-py asyncio 默认 `socket_timeout=5`(`redis/_defaults.py`),小于 `XREAD BLOCK 15000` 的服务端阻塞时长 → 空闲 5s 后 `xread` 必抛 `TimeoutError`(注意 `redis.exceptions.TimeoutError` 不继承内建 `TimeoutError`),chat 路由 `except Exception: return` 将其吞成空响应。生产环境一直靠浏览器 `Last-Event-ID` 自动重连掩盖。
  - 修复:`get_client` 显式 `socket_timeout=20`(> 最大 BLOCK 时长 + 余量,阻塞命令上线必检不变量);chat SSE 对 `RedisTimeoutError` 降级为心跳续命而非断流,其他总线异常 print 不吞错。
- **审批恢复把线程跨租户"搬家"(违反架构不变量 #1 多租户隔离,`engine_py/run_agent.py` + `approvals/`)**:
  - 根因:`_ensure_thread` 的 `ON CONFLICT DO UPDATE` 会覆盖已有线程的 `business_id`;而审批恢复派发(gatekeeper 同步 Fast-Path 与 outbox_worker 对账补偿)均未携带 `businessId` → 默认 `ecommerce` 直接改写 nike 租户线程归属,品牌配置、画像、会话列表全部错位。
  - 修复:upsert 只续 `updated_at`,线程租户归属创建时冻结;两处恢复派发显式携带审批单的 `record.business_id`,outbox payload 补 `businessId` 字段。
- **商户 SSE 中继消息延迟 15~30s (`gateway-py/routers/merchant.py`)**:
  - 根因:`get_message()`(默认 `timeout=0.0`)非阻塞轮询实测会吞一轮消息——消息已到达,第一次轮询仍返回 None,须下一轮才可见;叠加 `sleep(15)` 心跳节拍,每条 pub/sub 转发被拖一个完整周期。
  - 修复:改阻塞式 `get_message(timeout=15.0)`(客户端 socket_timeout=20 > 15 保证不误杀),实测转发 30.08s → 0.30s;顺带 `pubsub.close()` → `aclose()` 消除弃用告警。
- **asyncpg 对 uuid 列 raw SQL 绑定缺 CAST(审批 resolve 500 根因)**:gatekeeper ×3(含超时解挂的潜伏同类 bug)与 outbox_worker ×2 的 `UPDATE ... WHERE id = :id` 全部补 `CAST(:id AS uuid)`。
- **Alembic 0002 在全新库 `DuplicateTable`**:0001 基线是动态 `Base.metadata.create_all`(非冻结快照),后续迁移必须幂等 → 加 inspector 守卫,并固化约定。
- **健康路由缺统一包络**:`/api/health` 补 `success: true`。

### 🧪 Testing (测试基建)

- **契约套件首次全绿:29 passed / ~5s**(起点为迁移直接报错、整套跑不完;亦说明移植后从未完整执行过,本次等于把冻结契约真正钉死)。全程密封 testcontainers(PG 15 + Redis 7),任一裸机可复跑 `bun run test:eval`。
- **SSE 类测试统一切 `live_server` 真网络栈**:httpx `ASGITransport` 会把整个 ASGI app 跑到完成才进入 stream 上下文(body 全缓冲),"连接后灌事件/订阅后 publish"在 in-process 传输下结构性死锁——此前一次 22 分钟挂死即源于此。
- 商户流测试修复 httpx 流式响应二次迭代(`StreamConsumed`),改为单迭代内"connected → publish → 断言转发"。
- **macOS Docker Desktop 下 ryuk 必死**:默认 context 指向 `~/.docker/run/docker.sock`,该路径挂进 ryuk 容器不通 → 启动竞态与容器泄漏;conftest 按平台探测禁用 ryuk + atexit 兜底回收。
- gateway-py dev 依赖补 `aiohttp`(python-socketio AsyncClient websocket 传输前置,契约测试 `transports=["websocket"]` 所需)。

### ⚠️ Notes (注意事项)

- 涉及文件 ruff 检查与 HEAD 基线持平(仅自动整理 2 处新增 import 排序);存量告警(DTZ005/S110 等)未动。
- 阻塞命令使用约定:任何 `XREAD BLOCK` / `BLPOP` 类调用的 BLOCK 时长必须 < 客户端 `socket_timeout`(现 20s),新增阻塞调用前先核对该不变量。

---

## [2.3.0] - 2026-09-03 (坏例候选池闭环 v1、outbox 对账补偿修复、网关数据真实性清理)

### 🌟 Major Highlights (重大亮点)

- **坏例候选池与半自动闭环 (`engine_py/badcase/`,测试生命周期第五阶段 v1,2026-09-03 评审锁定 23 项决策)**:
  - 新表 `badcase_candidates`(Alembic `0002`):信号源、会话引用(`thread:` / `approval:` / `fact:`)、租户、先验类别、状态机 `candidate → confirmed/dismissed → converted`。**仓库零原始数据**——只存引用不存对话/画像原文。
  - 信号挂接(零契约变更):人工接管发起、审批驳回(`approvals/gatekeeper.py`)、画像事实删除(`gateway-py/routers/crud.py`)实时入池,携带信号先验(删除→`suspected_defect`、驳回→`expected_behavior`、接管→中性);入池失败静默降级不阻断宿主事务。
  - 熔断落盘:`run_agent` 检测全局转移 ≥10 或工具错误 ≥3 触发熔断时,以 `resolution_status='circuit_breaker'` 写入 `session_metrics`(新增 `global_transitions_count` / `tool_errors_count` 列),子任务指标不再计入。
  - 已知值脱敏(`badcase/redaction.py`):库内已知 PII(地址/收件人/手机号/邮箱)精确替换 ➔ `scrubber` 正则兜底的两层管道。
  - triage CLI(`python -m engine_py.badcase.cli`):`list / show(原文 vs 脱敏对照) / triage / draft / expire`;`draft` 只产 `expectedTools` / `not-contains` 断言(断言最小化,禁整句黄金答案),带 `origin: badcase:{id}` 溯源标记。
  - 保留期:candidate 90 天自动转 dismissed、dismissed 30 天清除(`badcase/digest.py`)。
- **周期任务框架与 outbox 对账补偿修复 (`engine_py/scheduler.py` + `approvals/outbox_worker.py`)**:
  - 原 outbox worker 为死代码(全仓无调用点)且旧实现存在"事件循环未运行静默返回"与"create_task 后立刻标 completed 的假完成"两个缺陷。重构为 `process_pending_events`:`FOR UPDATE SKIP LOCKED` 防多实例重复捞取、10s 年龄阈值避开与 gatekeeper 同步 Fast-Path 竞争、`processing` 停滞 >5min 重入队(重试上限 5)、派发任务自身回写终态(真完成)。
  - 新增 `scheduler.py` 单进程 asyncio 周期调度(间隔 + 抖动、逐 tick 容错):outbox 对账(30s)+ 坏例池摘要/保留期(6h);随 Temporal worker 入口启动,Temporal 离线时进程退化为纯周期任务进程仍在线。**单实例假设**,`ENGINE_SCHEDULER_ENABLED=0` 可整体关闭。
- **网关数据真实性清理 (`gateway-py/routers/crud.py`,契约增量字段、无路由变更)**:
  - `/api/logs` 接真实数据:intent 分支不再编造 `350/45/395/280` token/延迟假数(返回真实 0);metric 分支去掉 `or 1000` / `or 500` 兜底与虚构的 0.8/0.2 拆分;`rawDetail` 增量透出 `globalTransitionsCount` / `toolErrorsCount`。
  - `/api/evals/*` 响应显式携带 `isMock: true`(记录全部来自本地随机生成器),坏例看板/BI 数据源据此排除。

### 📝 Docs (文档同步)

- CLAUDE.md 不变量 #3、`.claude/rules/agent-engine.md` §1.6:outbox worker 表述由"从未被任何入口启动(技术债)"修正为"scheduler 每 30s 对账补偿"。
- `.claude/rules/agent-engine.md` 新增 §1.8(坏例候选池与周期任务);`database-schema.md` 补 `badcase_candidates` 表与 `session_metrics` 熔断列;`observability.md` 补熔断落盘;`server-gateway.md` 补 isMock/真实值约定与画像删除入池挂接。
- README §4.2 发件箱恢复机制描述与实现对齐(Fast-Path + 30s 对账,替代此前的"指数退避"误述)。
- `docs/agent-lifecycle-testing.md` 第五阶段落地批次:前置清理与 v1 标记已落地;附录技术债 #1(outbox 死代码)标记已修复。

### ⚠️ Notes (注意事项)

- pytest 契约套件按仓库约定未自动执行,需人工运行 `bun run test:eval`;`isMock` / `rawDetail` 增量字段如有精确匹配断言需同步契约测试。
- `docs/architecture/*.md` 仍整体为 TS 时代路径(77 处 `packages/` 引用),系迁移遗留债务,本次未零散修订,建议单独立案整体重写。

---

## [2.2.2] - 2026-09-03 (Python 后端运行时修复包: 商户 SSE 流 500、工具注册表解析失效、.env 环境注入)

### 🐛 Bug Fixes (缺陷修复)

- **商户端 SSE 流式通道 500 修复 (`gateway-py/src/gateway_py/routers/merchant.py`)**:
  - `/api/store/chat/stream` 曾以普通 `Response` 包装 async generator,Starlette `render()` 对非 bytes 内容调用 `.encode` 触发构造期 `AttributeError`,请求未写出任何响应头即 500。改用 `StreamingResponse`(与 `/api/chat/{jobId}/stream` 的既有惯例一致)。
  - 契约套件新增 `TestMerchantStoreChatStream` 回归钉:断言 200 + `text/event-stream` + `event: connected` 首帧 + Redis pub/sub 频道 `thread:{threadId}:message` 消息转发(此前该路由无任何契约覆盖)。
- **工具注册表解析失效修复 (`engine-py/src/engine_py/graph/nodes/step_execution_engine.py`)**:
  - 延迟导入 `..skills` / `..tools_registry` 相对深度少写一个点,实际解析到不存在的 `engine_py.graph.*` → `ImportError` 被优雅缺位逻辑吞掉 → Skills/Tools 解析器为 `None` → **全部 20 个电商工具**经执行引擎调度时一律落入 `"Tool or Skill ... not found in registry."`(症状首见于 `listUserOrders`)。修正为三个点(`...skills` / `...tools_registry`),恢复 Skills 优先、Tools 回退的调度链。
- **开发脚本 .env 环境注入修复 (`package.json`)**:
  - `dev:server` / `worker` / `db:push` / `db:seed` 统一改为 `uv run --env-file ../../.env ...`。此前 gateway 进程拿不到任何 `AI_*` 环境变量(`config.py` 只读 `os.environ`,dev 脚本也不注入),LLM base_url 回落到缺省的 `http://127.0.0.1:11211/...`(无服务监听),导致 validatorNode / finishNode / 画像 Profiler Agent 全线 `Connection error`;数据库与 Redis 仅因代码缺省值恰好与 dev 容器一致而"看似正常"。
  - README 快速启动章节补充 `.env` 准备步骤与环境变量自动加载说明。

---

## [2.2.1] - 2026-08-27 (意图去重旁路与画像审计自愈、富交互卡片闭环修复)

### 🌟 Major Highlights (重大亮点)

- **意图去重拦截器旁路修复与卡片透传保证 (`intentTriageEngine.ts`)**:
  - 在意图分流层的语义去重拦截器（`Triage Duplicate Shield`）中增加业务操作类指令（订单、物流、退款、导购等）豁免规则，杜绝连续/重复订单查询被静态缓存拦截而丢失富交互卡片。
  - 增强 `handleImmediateBypass` 逻辑，透传并保留现有卡片数据（`effectiveCards`），确保快速直达通道与前台 UI 卡片渲染不脱节。
- **画像审计专职 Agent 异步加载自愈 (`longMemory.ts`)**:
  - 修复 `LongMemory.runProfileAudit` 中动态加载 `db` 模块在 ESM/TS 运行时的 undefined 异常，改为静态顶层安全导入并执行 PostgreSQL 订单流水查询。
- **多模态卡片交互分发与选单链路闭环 (`FloatingChatWidget.tsx`, `ChatWidget.tsx`)**:
  - 在商户端与主站客户端浮窗中完善 `select_order`、`track_order`、`request_refund` 等富卡片交互事件派发与自动对话触发。

---

## [2.2.0] - 2026-08-27 (多模态订单选择弹窗、SPI 独立商户查单与状态回退增强)

### 🌟 Major Highlights (重大亮点)

- **多模态订单选择弹窗与富卡片交互 (`OrderPickerCard` & `cardSynthesizer.ts`)**:
  - 新增 `OrderPickerCard` 组件与弹窗选择交互模式，当用户查询多个订单时，以结构化弹窗形式完整展示订单编号、金额、承运商、运单号及履约状态。
  - 修复 `cardSynthesizer.ts` 中订单编号被错误截断（如 `ordId.slice(-8)` 导致 `AURORA-ORD-2026-9082` 变为 `026-9082`）的缺陷，确保全格式订单号展示与回调。
  - 移除冗余重复的快捷回复胶囊，统一由弹窗交互驱动选单与状态下钻。
- **SSE 流式通道与 HTTP 响应消息双向去重与卡片文本协同优化 (`FloatingChatWidget.tsx`, `finish.node.ts`)**:
  - 在商户端 API 路由统一 `messageId` 标识，并在客户端聊天浮窗中建立 SSE 流式推送与同步 HTTP fetch 响应的双重去重屏障，彻底解决“查询我的全部订单”等高频场景下出现重复两条气泡回复的竞态问题。
  - 优化 `finishNode` 总结生成规则，当交互式订单选择卡片已挂载时，避免在文本中冗余重复输出全量订单 Markdown 列表，实现图文协同轻量化。
- **多租户/SPI 独立商户订单查询与越权防御增强 (`orderDomainService.ts`)**:
  - 在 `findOrderById` 与 `getOrderStatus` 中建立从主站 `orders` 表到第三方独立商户 SPI 数据表 `third_party_orders` 的平滑回退检索机制，彻底解决商户独立订单查询时被误判为“越权阻止或未找到订单”的 IDOR 假阳性问题。
  - 完善订单商品明细关联（`third_party_order_items`），自动补全商品名称、单价及数量。
  - 同步适配 `changeShippingAddress` 与 `processRefund` 在三方商户订单表中的状态变更。
- **全格式订单编号正则与意图消歧提取修复 (`utils.ts`, `intentTriageEngine.ts`, `planner.node.ts`)**:
  - 升级订单号正则识别规则（匹配带有品牌前缀与多段横杠的订单号，如 `AURORA-ORD-2026-9081`），确保意图分流、槽位提取及规划节点准确提取实体。
- **文档与测试套件完善**:
  - 新增 `apps/merchant/tests/merchantCardInteractionFlow.test.ts` 订单卡片选择与物流查询端到端全链路测试套件。
  - 在 `README.md` 与 `docs/merchant-onboarding-guide.md` 中补充 Agent SOP 业务技能开发、商户对接与测试实战指南。

---

## [2.1.0] - 2026-08-26 (多轮导购序号指代消解与商户端实时流式会话升级)

### 🌟 Major Highlights (重大亮点)

- **多轮导购序号指代消解与购物车上下文跨轮次持久化 (Multi-Turn Shopping Guide Ordinal Resolution & Cart Coreference)**:
  - 彻底打通从“导购推荐商品”到“把第1件加入购物车”、“买第2款”、“把第几件加入购物车”等多轮自然语言指代消解与加购闭环。
  - 在 `ShoppingGuideContext` 中引入 `candidateProducts` 结构化元数据（包含真实商品 ID、名称、单价、库存、规格与配图），解决上下文仅有基础 ID 缺乏商品快照的问题。
  - 强化 `TaskMemory` 跨请求任务状态管理，将 `guideContext`、`cartContext`、`orderContext` 深度持久化至 PostgreSQL `pending_intents`，并在图构建启动时自愈恢复，根除无状态 HTTP 导致的跨轮次推荐上下文丢失。
  - 升级 `CartManageSkill` 与 `slotExtractor.ts`：
    - 支持精准提取中文及阿拉伯数字序号（“第1件”、“第一款”、“第二件”等），自动映射到 `guideContext.candidateProducts` 并调用 `MallDomainService.addToCart`；
    - 支持短期对话历史（`shortMemory`）回溯兜底，若上下文丢失可自愈解析历史推荐消息；
    - 针对用户原样输入或复制引导语“把第几件加入购物车”提供智能友好提示与候选列表引导。
  - 新增 `packages/engine/tests/shoppingToCartMultiTurn.test.ts` 5 轮端到端全链路自动化集成测试。
- **商户端实时 SSE 流式推送与会话隔离优化 (Merchant SSE Stream & Session Isolation)**:
  - 彻底移除商户端前端浮窗 3 秒高频 HTTP 轮询，改用基于 Server-Sent Events (SSE) 协议的实时事件流（`/api/store/chat/stream`），大幅降低服务端无谓开销并提升交互即时性。
  - 优化新会话初始化与隔离逻辑：刷新或新建会话时展示专属路由问候语，隔离旧会话霸屏，同时支持通过历史记录面板按需恢复与回放既往对话。
- **多段式订单编号支持与会话回放增强 (Multi-Segment Order IDs & Timeline Playback)**:
  - 增强订单编号正则与提取器，支持包含多段横杠与复杂前缀的真实商户订单号。
  - 优化控制台全景会话工作台的实时坐席同步与抽屉历史流式回放。

---

## [2.0.0] - 2026-08-24 (重大架构重构与 SaaS 平台升级)

### 🌟 Major Highlights (重大亮点)

- **NestJS 企业级 API 网关与标准化契约 (`apps/server`)**:
  - 彻底解耦传统单体服务，构建基于 NestJS 核心框架的企业级 API Gateway，统一管理路由分发、依赖注入（DI）、全局异常过滤器与日志切面。
  - 规范 RESTful API 路由设计（涵盖 `/api/chat`、`/api/skills`、`/api/tenants`、`/api/tools` 等）。
  - 全局启用 `ValidationPipe({ forbidNonWhitelisted: true, whitelist: true, transform: true })`，严格阻断未知字段与参数注入，建立坚实的多租户物理与逻辑边界。
- **多租户 SQL 物理层下推隔离与越权防御 (Physical SQL Push-Down Tenant Isolation)**:
  - 彻底改造底层数据仓储与审批流核心方法（如 `ConversationRepository.getConversationTimeline`、`ApprovalGatekeeper.listPendingApprovals` 等），强制将 `business_id` 参数下推至 PostgreSQL 物理 SQL 约束（`WHERE business_id = $1`），彻底杜绝全表加载后在应用层 JavaScript 内存过滤带来的越权风险（IDOR）与内存泄漏隐患。
  - 重构 `TenantRegistryService.updateTenantSkillConfig`，采用安全的物理主键查更机制取代脆弱的 `ON CONFLICT` 语法，完美兼容版本化多租户配置表。
- **实时协同坐席接管与 SSE 流式弹性回放机制 (Live Desk Takeover & SSE Stream Resiliency)**:
  - 落地 WebSocket 双向即时坐席接管网关（`ConversationGateway`），基于 Socket.io 与 Redis Pub/Sub 实现分布式会话接管。坐席端一键发起 `takeover_conversation`，会话状态机原子跃迁至 `human_takeover` 并即时暂停 AI 自动回复；释放时通过 `release_takeover` 毫秒级归还 AI 托管。
  - 在 `ChatService` 中构建跨连接 Job 级事件缓存队列（`jobEventStore`）与单调递增序列号体系（`id: ${seq}`）。当客户端因网络抖动重连并携带 `Last-Event-ID` 请求头时，服务端精准回放掉线期间丢失的思考步骤（`thought`）、工具调用（`tool`）、富媒体卡片（`cards`）与最终结果（`result`），保障多模态对话流 100% 幂等与无缝连续。
- **Admin SaaS 控制台全面重构与 10 大路由 CRUD 模块 (`apps/admin`)**:
  - 基于 React Router 7 + `@agent-all/ui` 纯组件重构企业级 SaaS 控制台，完整落地 10 大标准业务管理子系统：
    1. **商户入驻与管理 (Tenants)**：多租户生命周期与品牌心智配置；
    2. **技能编排中心 (Skills)**：SOP 技能启闭、审批阈值与自定义 Prompt 动态生效；
    3. **工具注册中心 (Tools)**：OpenAPI 动态工具工厂与 MCP/SPI 插件元数据治理；
    4. **HITL 审批工作台 (Approvals)**：敏感业务操作人机协同核签抽屉与状态机流转；
    5. **全渠道会话工作台 (Conversations)**：多租户会话全景树、深层链路 Trace 追溯与实时坐席接管；
    6. **双层用户画像中心 (Personas)**：全局基础生理偏好与租户专有消费习惯分层管理；
    7. **RAG 知识库工坊 (RAG Studio)**：分块检索演练场、切片预览与幂等入库管理；
    8. **安全合规护栏 (Guardrails)**：Prompt 注入防御策略、PII 脱敏规则与风控红线配置；
    9. **大模型评测中心 (Evals)**：自动化 Promptfoo 评测集管理与指标准确率矩阵看板；
    10. **用量与账单中心 (Billing)**：租户级 Token 算力消耗明细、换算成本与财务配额限制。
  - 提炼标准化、零外部组件库依赖的通用 CRUD 套件（`useAdminCrud`、`DataTable`、`FilterBar`、`DetailDrawer`、`FormModal`、`ConfirmDialog`），无缝对接 NestJS API Gateway。
- **BaseSkill 领域技能编排与开放集成生态 (`packages/engine`, `packages/tools`)**:
  - 所有领域技能统一继承 `BaseSkill` 标准抽象类，实现 `canHandle` ➔ `validate` ➔ `execute` ➔ `postExecute` 四阶段标准流水线。
  - 支持商户针对不同技能单独配置启用状态（`enabled`）、免签核准阈值（`approvalThresholdAmount`）以及定制化 SOP 提示词（`customPolicyPrompt`），实现零代码热更新。
- **AST 参数化 NL2SQL 沙箱、双层用户画像与 Transactional Outbox (Security, Persona & Outbox)**:
  - NL2SQL 采用 AST 抽象语法树校验，硬性限制仅允许执行 `SELECT` 查询，强制注入租户物理边界与 `LIMIT 50` 分页保护，并在只读短事务内执行。
  - 落地 Dual-Tier Persona 架构：物理区分 `scope = 'global'`（跨商户通用客户画像）与 `scope = 'tenant'`（品牌私有画像），兼顾个性化服务与商户数据隔离合规。
  - 引入金融级 Transactional Outbox 机制 (`approval_outbox_events`)，保障人机协同审批状态变更与异步工作流恢复的严格原子性与最终一致性。
- **标准化自动化测试套件与持续回归保障**:
  - 新增 `codeReviewFixes.test.ts` 专项测试，针对多租户物理 SQL 下推隔离、SSE 断线重放机制、Skills RESTful 配置 API 进行全量断言验证。
  - Monorepo 全量单元测试、集成测试及 Admin 控制台自动化套件持续保持 100% 绿色通过。

---

## [1.11.0] - 2026-08-22

### 🌟 Major Highlights (重大亮点)

- **工单审核全链路客户身份穿透与长期画像偏好展示 (Approval Identity Resolution & Customer Persona)**:
  - 解决工单列表、工单审核详情抽屉与独立 IM 弹窗中客户身份缺失及画像无法获取的问题。
  - 在 `approvalService.ts` 中通过 `leftJoin(users, eq(threads.userId, users.id))` 实现会话与用户账户的物理关联合并投影，直接透传 `userEmail` 与 `userId`。
  - 扩展 `/api/chat/preferences` 接口支持 `?userId=...` 参数化精准过滤，并关联用户邮箱。
  - 全面升级工单详情抽屉（`ApprovalDetailView`）、人工客服 IM 实时工作台（`HumanChatModal`）与工单列表（`ApprovalList`）：直观展示实名客户邮箱、UUID、商户标识，并动态渲染客户在 `long_memory_facts` 中沉淀的长期画像偏好标签（如尺码偏好、材质避雷、品牌偏好及提取置信度）。
- **RAG 知识库切片物理去重与幂等入库体系 (RAG Ingestion Idempotency & Deduplication Engine)**:
  - 彻底根除 `rag_documents` 物理表中由于反复执行测试与导入导致的切片数据与 Embedding 向量冗余污染（通过 `check-and-clean.ts` 物理清理 574 条重复记录）。
  - 在全链路知识库入库管道（`ingestTxtFiles.ts`、`updateRag.ts`、`seed-rag.ts` 及 `/api/tenant/knowledge/upload`）落地原子化预清理与唯一键检查策略，确保知识入库全流程具备 100% 幂等性。
  - 新增 `packages/engine/tests/ragDeduplication.test.ts` 专属去重与幂等入库防回归测试套件。
- **细粒度 LLM 算力调用审计与低置信度意图主动学习归档 (Granular LLM Telemetry & Active Learning Logging)**:
  - 激活 `llm_call_logs` 物理审计追踪：在 `callLLMWithRetry.ts` 中深度捕获单次 LLM 调用的 Prompt Tokens、Completion Tokens、单次调用耗时（`latencyMs`）、财务成本换算（`costUsd`）、LangGraph 节点名称（`triage`, `planner`, `executor`, `validator`, `finish`）、模型 ID 及 `threadId`。
  - 激活 `low_confidence_logs` 主动学习归档：在 `intentTriageEngine.ts` 中当意图置信度 $<0.65$ 时自动归档用户原始输入与候选意图概率分布，用于线上意图漂移分析与提示词调优。
- **全链路自动化测试套件回归 (Full Test Suite Regression)**:
  - 全量 161 个测试用例（覆盖 47 个测试文件、786 个断言）全部 100% 绿色通过。

---

## [1.10.0] - 2026-08-22

### 🌟 Major Highlights (重大亮点)

- **PostgreSQL 确定性角色时序排序与历史对话防错乱引擎 (Deterministic Message Ordering & Monotonic Clock)**:
  - 彻底根除刷新页面后对话历史次序颠倒（AI 回复跑到用户提问前）的顽疾。
  - 在 `packages/db/src/client.ts` 物理查询层引入确定性角色权重排序：`ORDER BY timestamp ASC, CASE role WHEN 'system' THEN 1 WHEN 'user' THEN 2 WHEN 'assistant' THEN 3 ELSE 4 END ASC, id ASC`，消除同一毫秒并发写入导致 UUID 字典序随机颠倒的缺陷。
  - 在 `packages/engine/src/memory/shortMemory.ts` 引入基于逻辑时钟的角色单调递增时间戳生成机制（`getMonotonicTimestamp`），保证 `assistant` 响应在时钟逻辑上严格晚于 `user` 提问。
  - 通过 `packages/engine/tests/messageOrdering.test.ts` 并发时序验证，确保全场景历史记录 100% 严格按先后交互顺序呈现。
- **SaaS 多租户品牌身份物理锚定与动态脱敏 (Multi-Tenant Brand Identity Anchor & JIT Sanitization)**:
  - 修复多租户会话中商户品牌（如 Nike、Adidas）在历史消息中被降级为 `[ECOMMERCE]` 占位符的问题。
  - 强化 `db.createThread` 租户保护屏障：现有商户会话拒绝被未指定或默认的 `ecommerce` 身份覆盖。
  - 在 `/api/chat/messages` 接口层引入 `sanitizeTenantResponse`，在历史记录拉取阶段结合会话所属商户动态清洗品牌心智。
- **输入框生命周期管理与即时清空机制 (Chat Input State Lifecycle & Instant Clearing)**:
  - 修复发送消息后输入框依然残留上一轮文本的交互缺陷，解耦表单提交与发送逻辑。
  - 在 `ChatArea.tsx` 的 `onSubmit` 与 `useChatMessages.ts` 的 `handleSend` 中实现状态无条件清空，并清空附件图片列表。
  - 增加 `apps/web/tests/chatInputState.test.ts` 单元测试验证输入状态生命周期。
- **人工客服接管生命周期与乐观加载态隔离 (HITL Takeover Lifecycle & State Isolation)**:
  - 修复转人工后用户继续提问导致界面永久卡在“正在全速运行多模态有向有环图节点，智能调用工具链中...”以及 AI 错误抢答的缺陷。
  - 在 `useChatMessages.ts` 收到 `isHumanActive: true` 时立即清理乐观加载态（`isLoading: true` / `pending-job`），并调用 `loadHistory(force=true)` 同步真实数据库消息。
  - 严格保障人工客服接管期间（`status = 'waiting'`）用户消息直通数据库并实时同步，直到人工专员明确点击“🏁 结束人工服务 (切回 AI)”（`status = 'resolved_by_human'`）后才平滑恢复 AI 智能调度。
- **运行时连接池单例化与 HMR 缓存防护 (GlobalThis Singleton Pool Management)**:
  - 修复 Next.js 热重载（HMR）过程中反复建立物理 PostgreSQL 连接池、Redis 客户端和 Temporal Client Promise 的问题，统一通过 `globalThis` 实现单例生命周期管理。

---

## [1.9.0] - 2026-08-21

### 🌟 Major Highlights (重大亮点)

- **商城全功能数据库体系与领域服务 (Comprehensive E-Commerce Schema & Mall Domain Service)**:
  - 物理构建高标准 SaaS 关系型商城数据库结构：
    - `user_addresses`: 用户多地址簿（默认地址、详细门牌、收货人与联系电话）；
    - `product_skus`: 商品多规格属性（尺码、颜色、SKU 编码、库存与差异化价格）；
    - `logistics_packages`: 订单履约包裹表（多包裹拆单履约、承运商与主运单号）；
    - `logistics_tracks`: 物流时序轨迹流水（时间戳、物理节点站点、派送状态与描述）；
    - `product_reviews`: 用户商品评价与晒单（星级打分、文本评论与图片证据）；
    - `after_sale_tickets` & `after_sale_logs`: 售后服务工单与流转状态机跟踪。
  - 封装 `MallDomainService` 领域服务，提供标准查询与状态流转接口。
- **意图-槽位状态机与缺失参数即时反问机制 (Intent-Slot State Machine & Fast-Path Clarification)**:
  - 实现结构化槽位与意图抽取器 `SlotExtractor`，严格定义高风险业务必填槽位映射表 `REQUIRED_SLOTS_MAP`（如修改收货地址必须具备 `orderId` 与 `newAddress`）。
  - 在 `IntentTriageEngine` 阶段引入槽位缺失拦截守卫，参数不足时毫秒级生成即时精准反问并写入 `TaskMemory` 多轮上下文记忆；参数补齐后高置信度放行直达 DAG 调度，彻底阻断由于缺少参数导致的自旋与大模型幻觉。
  - 接入 Promptfoo 专属槽位评测集 `slot-clarification.json` 与 `slotClarification.scorer.ts` 自定义评分器，评测通过率 100%。
- **Temporal 真实编排实时状态 SSE 桥接与防假死架构 (Temporal SSE Real-Time Status Stream)**:
  - 重构 `/api/chat/[jobId]/stream` 路由，在真实 Temporal 模式下建立 300ms 毫秒级 `currentStatusQuery` 与 `currentPlanQuery` 轮询推送机制，将底层节点执行状态实时桥接至 Web UI。
  - 在 LangGraph `buildAgentGraph` 及 Temporal `agentWorkflow` 中统一 `isBypass` 判定守卫（`state.output` 存在或 `bypass_step`），保证槽位即时反问与规则旁路毫秒级直达 `finishNode`，避免误入 Planner 自旋。
- **泛订单查询极速直达与批量富媒体卡片合成 (Fast-Path Order Listing & Rich Card Batching)**:
  - 细化泛查单意图与单笔物流追踪正则边界，消除“我的订单”被误拦截为缺失单号追问的缺陷，极速直达 `listUserOrders` 调度。
  - 扩展 `CardSynthesizer` 引擎支持 `result.orders` 批量订单交互卡片生成（查看物流轨迹、申请退款按钮及智能快捷回复胶囊），并内置多租户演示订单自动自愈机制。
  - Monorepo 全量 122 项单元与集成测试 100% 绿色通过（578 个断言）。

---

## [1.8.0] - 2026-08-21

### 🌟 Major Highlights (重大亮点)

- **Text-to-SQL 与 Headless BI 指标语义注册表体系 (Metric Semantic Registry v2)**:
  - 落地 `MetricDefinition v2` 契约标准，将 SQL 聚合公式、动态模板、业务规则约束、口语同义词、歧义冲突组（`conflictGroup`）、排序及展示单位结构化声明配置，从根源上杜绝大模型口径幻觉与硬编码 `if/else`。
  - 预置商场多维指标元数据字典（GMV 总销售额、出货销量件数、净毛利润收益、单品毛利率、滞销积压库存预警）。
  - 实现 `MetricSemanticResolver` 智能指标匹配器，自动识别自然语言同义词与冲突组（如 GMV 流水 vs 出货件数 vs 净毛利润 vs 毛利率）。
- **六大正交解耦 NL2SQL 查询语法树解析与动态编译器 (`packages/tools/src/nlQuery/`)**:
  - `TextNormalizer`：入口前置清洗语气词与虚词（“帮我/麻烦看一下/给我展示/对比看看”等），保护语义纯净度。
  - `TimeRangeResolver`：独立解析时序范围（“近30天/上个月/近7天/今年”），自动输出参数化 PostgreSQL 时间过滤子句。
  - `OrderLimitResolver`：解析“销售额最低/倒数/最少”等反向排序指令并动态改写 `directionOverride`，同时精准提取 TopN 数量限制。
  - `DimensionResolver`：动态解析分组维度（“按品类看/按商品维度”），解耦指标与 GROUP BY 物理列。
  - `FilterResolver`：解析“库存大于500/价格低于200/品类是鞋类”等多维数值与枚举过滤条件。
  - `NLQueryCompiler`：结合多租户上下文、负责人 `managerId` 与 AST 语法树动态安全渲染参数化物理 PostgreSQL 语句，支持防除零安全保护。
- **商场物理数据库扩展与多维分析服务 (`OrderDomainService.queryProductRanking`)**:
  - PostgreSQL 物理迁移：`products` 表扩充 `manager_id`、`category`、`cost_price` 字段，`order_items` 表扩充 `cost_at_purchase`（下单成本快照，防后续商品改价失真）。
  - 注入高保真商场种子数据（覆盖 Vaporfly 顶级竞速鞋、飞马跑鞋、长筒袜等不同销量/流水/毛利特性的商品与订单）。
- **声明式槽位消歧引擎与富交互卡片闭环 (`SlotDisambiguationEngine` & `ProductRankingCard`)**:
  - 实现通用槽位消歧引擎，结合 LongMemory 用户画像与 Default 策略推荐最佳指标。
  - `CardSynthesizer` 自动合成带有金银铜牌徽章、单价、累计销量、GMV 流水、净毛利润与毛利率的 `ProductRankingCard`。
  - 在卡片底部自动挂载 Quick Replies 一键切换口径胶囊（💰 按总销售额 / 📦 按出货销量 / 📈 按净毛利润 / 🎯 按单品毛利率 / ⚠️ 排查滞销库存），实现人机交互与口径切换闭环。
- **Promptfoo 质量评测与 Monorepo 全量测试保障**:
  - 新增 `eval/scorers/metricDisambiguation.scorer.ts` 与 `eval/testCases/ecommerce/metric-disambiguation.json` 评测用例集并在 `promptfooconfig.yaml` 中注册；
  - Monorepo 全量 100 个单元与集成测试 100% 绿色通过（494 个断言）。

---

## [1.7.0] - 2026-08-20

### 🌟 Major Highlights (重大亮点)

- **多模态视觉感知与智能破损定责系统 (Multimodal Vision & Damage Assessment)**:
  - 引入 `VisionAnalyzerService`，在 Triage 首层直接支持图文多模态意图识别、快递面单 OCR 提取（运单号/订单号）与商品破损瑕疵智能定级（`negligible` / `minor` / `severe`）。
  - 内置手机号、身份证、银行卡 PII 敏感信息脱敏过滤器，并具备 1500ms 视觉超时与启发式降级兜底。
- **富交互结构化卡片与统一渲染引擎 (Rich Interactive Cards & Synthesizer)**:
  - 新增 `CardSynthesizer` 引擎与统一协议标准（`order_card`、`tracking_timeline`、`refund_confirmation`、`damage_assessment`、`quick_replies`）。
  - 在 `packages/ui` 中构建原生 SVG 图标的高保真卡片组件族与 `RichCardRenderer`，支持一键查看物流、申请退款、动态快捷回复胶囊交互。
- **图片安全上传端点与客户端多图预览 (Safe Image Upload & Client Preview)**:
  - 新增 `/api/chat/upload` 统一接口，强制校验 MIME Type（JPG/PNG/WebP/GIF）与 10MB 大小边界，落盘至持久化目录。
  - 前端输入区集成“📎 图片上传/粘贴”预览条与快捷移除卡片。

---

## [1.6.0] - 2026-08-20

### 🌟 Major Highlights (重大亮点)

- **SaaS 商户自主入驻与配置中台 (Self-Service Tenant Hub & IAM)**:
  - 引入 `tenants`、`tenant_members`、`tenant_configs` 与 `tenant_tools` 实体，规范单层商户模型 (`businessId` 命名空间) 与 `Owner` / `Admin` / `Agent` 三级 RBAC 权限隔离。
  - 实现提示词与品牌心智配置的草稿调试（`draft`）与生产发布（`published`）双状态生命周期。
- **商户 API 凭证安全加密与运行时 JIT 脱敏 (Secrets KMS & JIT Injection)**:
  - 基于 Node.js 原生 `crypto` 与 RFC 5869 HKDF，利用主密钥与租户 ID 派生独立密钥，实施 `AES-256-GCM` (`iv:authTag:ciphertext`) 高强加密存储。
  - 动态工具调用时实行 JIT 即时解密注入 Header，全链路脱敏 Pino 日志、Langfuse Span 与 SSE 推送流。
- **OpenAPI 3.0 动态工具工厂与 SSRF 运行时安全沙箱 (Dynamic Tools & SSRF Guard)**:
  - 动态解析 OpenAPI JSON 并生成 Zod Schema 校验器，自动将 `x-requires-approval` 与变更路径路由至 HITL 待审批队列。
  - 内置 DNS 预解析与私网网段（`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `169.254.169.254`）硬拦截 SSRF 运行时沙箱，并施加 8 秒物理超时熔断。
- **知识库多格式异步切片与 Contextual RAG 摄入流水线 (Document Ingestion Pipeline)**:
  - 实现递归段落边界分块（~600 tokens 目标大小，100 tokens 重叠）并自动生成 Anthropic 标准情境摘要，批量注入 PostgreSQL `rag_documents`。
- **租户管理与配置 REST API 路由**:
  - 新增 `/api/tenant/onboard`、`/api/tenant/config`、`/api/tenant/tools` 与 `/api/tenant/knowledge/upload` 统一接口。

---

## [1.5.0] - 2026-08-20

### 🌟 Major Highlights (重大亮点)

- **纯物理真实 PostgreSQL 数据库架构 (Single Source of Truth)**: 彻底移除了 600+ 行内存模拟库（`FakePool`）及复杂的 SQL 正则匹配与降级分支，系统所有读写操作均直连物理真实 PostgreSQL 数据库与 Drizzle ORM，彻底杜绝数据脱节与幽灵数据。
- **聊天记录单调时序与会话级强隔离 (Message Ordering & Session Isolation)**:
  - 在 `ShortMemory` 与 `AgentMemoryEngine` 中引入单调递增时间戳与严格串行入库，数据库查询增加 `ORDER BY timestamp ASC, id ASC`，彻底解决高频与并发写入下刷新页面消息时序颠倒混乱的问题。
  - 重构前端 `useChatMessages` 与 `useChatThreads`，通过活跃会话 Ref 竞态防护拦截迟到异步响应，并在新建与切换会话时立即重置界面为默认欢迎语，彻底消除旧会话历史残留穿透。
- **公共标准订单创建领域服务 (`createOrder`)**: 在 `OrderDomainService` 中新增并暴露了标准 `createOrder` 工具，自动关联用户会话、多租户（SaaS Tenant）归属与订单明细条目，并在落盘后自动同步清除 Redis/本地缓存。
- **Admin 控制台客服介入 IM 工作台统一 (`HumanChatModal`)**: 抽离统一的 `packages/ui/src/components/chat/` 模块，配置 Tailwind CSS v4 `@source` Monorepo 扫描规则，彻底解决 Admin 工作台独立编译下的弹窗样式错位变形。
- **意图分流防误拦截 (Zero False-Positive Refund Interception)**: 优化 `intentTriageEngine`、`executorFastPath` 与 `stepExecutionEngine`，消除纯订单查询被误拦截为退款流程的逻辑缺陷。

### 🏗️ Major Refactoring (重大重构)

- **移除内存数据库模拟器 (`b05abd4`)**: 彻底删除了 `packages/db/src/fakePool.ts`，简化 `packages/db/src/client.ts` 使得所有 API、Agent 与工具直连真实 `pg.Pool` 连接池。
- **统一 HITL 审批中台组件与领域服务 (`11127ff`, `abd1832`)**: 对 HITL 审批工单、人工客服 IM 接管弹窗、订单领域服务及跨包类型进行了全量模块化收敛与编译修复。

---

## [1.4.0] - 2026-08-19

### 🌟 Major Highlights (重大亮点)

- **子任务并行执行器 (Parallel Subtask Executor)**: 在 `StepExecutionEngine` 中实现了基于 `Promise.all` 的无依赖子任务并行调度器，多意图复合查询执行延迟物理降低 50%+。
- **PII 敏感数据物理脱敏拦截器 (PII Scrubber Middleware)**: 在 `packages/tools` 中上线递归敏感数据脱敏切面，自动掩码手机号、身份证、银行卡号与邮箱，保障日志与 Trace 架构合规。

### 🚀 Features & Enhancements

- **并发子任务并行调度 (`cb52316`)**: 重构 `StepExecutionEngine`，自动检测 Fast-Path 独立子任务队列并通过 `Promise.all` 并发极速调起工具，极大缩短用户等待时间。
- **工具链 PII 脱敏切面 (`cb52316`)**: 统一封装 `registerTool` 执行层，所有工具输入/输出参数自动进行 PII 物理数据掩码。
- **TTFT 测速与压测大盘升级 (`cb52316`)**: 升级 `scripts/load-test.ts`，增加流式 SSE 首字响应延迟 (Time To First Token, TTFT) 检测与多租户并发测试能力。

---

## [1.3.0] - 2026-08-14

### 🌟 Major Highlights (重大亮点)

- **多意图分析与 Fast-Path 多步骤直达**: 实现了对多意图（如“查询物流+申请退款”）的精准识别、主次意图加权（Primary/Secondary Weighting）以及槽位提取，并在关联订单号时提供秒级极速直达通道（无需 LLM 规划消耗）。

### 🚀 Features & Enhancements

- **类型升级 (`30d6c25`)**: 为 `IntentResult` 增加了 `type` 与 `entities` 槽位，使分类图节点具备复合诉求提取能力。
- **极速调度优化 (`30d6c25`)**: 拓展 Planner 节点的 Fast-Path，支持复合意图直接组装多步骤子任务 DAG 链，将首字与步骤生成延迟降低 1.5s ~ 2.0s。

---

## [1.2.0] - 2026-08-12

### 🌟 Major Highlights (重大架构升级)

- **深模块门面重构 (Deep Module Facade Clean Up)**: 将原本膨胀的单体模块彻底拆解，提升系统测试性与可维护性。
- **Anthropic Contextual RAG 热更新管线**: 构建集 Markdown Chunking、Contextual Summary 提取、YAML Frontmatter 标注与零样本（Zero-shot）分类于一体的 RAG 数据入库管线。

### 🏗️ Major Refactoring (重大重构)

- **四层记忆统一门面 (`AgentMemoryEngine`) (`7aae5be`)**: 封装 Short、Long、Task、Episodic 四层记忆，实现单次并行获取 (`gatherContext`) 与增量并发归档 (`recordTurn`)。
- **网络流与 UI 渲染解耦 (`AgentStreamClient`) (`7aae5be`)**: 抽离 SSE 订阅客户端，彻底消除 React 渲染树对 EventSource 生命周期的依赖。
- **双模工作流统一调度器 (`WorkflowOrchestrator`) (`7aae5be`)**: 统一 Temporal 生产引擎与本地 LangGraph 极速模拟器的调度与降级逻辑。
- **安控网关拆分 (`StepExecutionEngine` & `ApprovalPolicyEngine`) (`7aae5be`)**: 将 800+ 行单体执行节点解耦为任务执行引擎与金融红线校验网关。
- **数据库仿真隔离 (`FakePool`) (`7aae5be`)**: 从 Drizzle 客户端解耦，提供隔离的 12+ 张关系型表的内存 SQL 仿真。

### 🚀 Features

- **SOP 生产上线标准检查清单 (`687f9dc`, `029e6f7`)**: 在 `README.md` 中集成包含数据库 Migration、Quotaguard 防刷、CircuitBreaker 熔断与 20 并发高吞吐压测脚本的生产上线 SOP 指南。

---

## [1.1.0] - 2026-08-11

### 🌟 Major Highlights (重大重构)

- **全局类型安全与领域仓储隔离**: 彻底剥离全代码库中的 Loose `any` 隐式类型，提炼独立的 `packages/types` 基础包。
- **人工客服 IM 实时接管系统**: 实现 LLM 断路触发、一键人工接管对话（`start_human_takeover`）及对话流安全挂起与恢复。

### 🏗️ Refactoring

- **独立类型共享包 (`packages/types`) (`d2e058f`, `d1a168c`, `b399025`)**: 按 `agent`, `approval`, `config`, `log`, `db`, `event`, `observability`, `tool` 进行模块化强类型声明。

### 🚀 Features & Fixes

- **断路器与人工客服 IM (`78b1e42`)**: 支持客服主管在控制台发起实时 IM 接管，安全打断 AI 决策，并在完成后平滑恢复 AI 智能应答。
- **Fast-Path 规划旁路 (`825b6ae`)**: 实现单意图查询/退款的零 LLM 消耗单步计划合成。

---

## [1.0.0] - 2026-08-10

### 🌟 Major Milestone (1.0 稳定版发布)

- **金融级多租户隔离与账单审计上线**: 正式落地 SaaS 多租户 SQL 物理隔离、Redis SETNX 分布式并发锁与高精度财务算力计费大盘。

### 🚀 Features

- **SaaS 物理隔离与分布式锁 (`537f794`)**: ORM 物理附加 `business_id` 过滤；引入 Redis SETNX 分布式并发防重入锁与 5s 短 TTL 内存降级锁。
- **算力审计大盘 (`537f794`)**: 异步写入 `session_metrics` 账单，提供毫秒级决策时效与 Autopilot 放行率统计。

---

## [0.9.0] - 2026-08-04

### 🔧 Stability & Critical Fixes (稳定性加固)

- **管道缺陷修复 (`66f2e73`)**: 修复包含高价值订单地址变更审核拦截、引用指针失效、死循环熔断以及数据库降级崩溃等 7 个关键 Pipeline Bug。
- **滑动历史窗口与容器防冻保护 (`eb26e4d`)**: 实现对话历史滑动窗口截断，增加 Serverless 容器解冻保护（`waitUntil`）。

---

## [0.8.0] - 2026-07-30

### 🚀 Performance & Multi-Turn Intelligence (性能与上下文优化)

- **Triage 极速优化 (`9567a8a`)**: 引入全局向量缓存（`embeddingCache`）与 Anchor 例句批量向量预加载，大幅提升意图分类速度。
- **上下文感知精判 (`8958721`, `ba10032`)**: 升级大模型意图分类 Prompt，使其具备结合前 4 轮历史上下文的深层语义理解能力。

---

## [0.7.0] - 2026-07-29

### 🏗️ Workspace Modularization (工作空间与 UI 重构)

- **解耦独立应用 (`0075c26`, `e086c89`)**: 将管理控制台（Admin）与用户主站（Web）迁移至 `app/home`，拆分为高内聚组件与 Hooks。
- **共享 UI 基础设施 (`da78d6d`, `f758aaa`)**: 抽离独立的 `packages/ui` 基础包，统一 Lucide Icons 图标导出与 Tailwind 样式模板。
- **HITL 轮询感知器 (`286037d`, `916abe5`)**: 实现前端高保真人工审核工单同步感知传感器，彻底解决多端并发状态竞争问题。

---

## [0.6.0] - 2026-07-28

### 🛡️ Security & Profiling (安全红线与用户画像)

- **IDOR 水平越权拦截 (`e9dc57f`)**: 物理拦截跨用户访问他人订单的 IDOR 漏洞。
- **异步画像 Agent (`5544d78`)**: 引入后台异步 `UserProfileAgent`，自动从多轮对话中提炼客户消费偏好与尺码卡片。
- **多租户物理沙箱 (`cc61d67`)**: 实现知识库向量检索的物理租户隔离沙箱与图级别死循环硬熔断。

---

## [0.5.0] - 2026-07-27

### 🚀 Admin Audit Desk & Advanced RAG (管理大屏与高级 RAG)

- **独立 Admin 中台 (`64698b6`, `6d74046`)**: 创建 Next.js 独立 `apps/admin` 管理工作区，部署可视化人工核签与审核大屏。
- **高级数学 RAG 混合检索 (`1a81b23`)**: 废弃简单关键字匹配，实现 Portable BM25 算法与 Reciprocal Rank Fusion (RRF k=60) 倒数排名融合。
- **自动化 Promptfoo 评测平台 (`5e53191`, `5c59226`)**: 搭建涵盖 Prompt 越狱防范、工具调用准确率与 LLM-as-a-judge 的自动化评估套件。

---

## [0.1.0] - 2026-07-24

### 🐣 Initial Project Release (项目初始发布)

- **智能客服中台初始化 (`3939a76`)**:
  - 核心 LangGraph Agent 决策图 (`triage` → `planner` → `merge` → [`executor` ⇄ `validator`] → `finish`) 构建。
  - 人工核签与认知回溯（HITL & Cognitive Backtracking）机制落地。
  - PostgreSQL + Drizzle ORM + Redis 架构搭建。
  - 支持 Nike / Adidas 多商户动态配置与退款免签额度防线。
