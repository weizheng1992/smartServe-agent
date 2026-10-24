---
description: 商户独立后台(数据分析 Agent/RBAC/优惠/订单商品客户 CRUD):悬浮助手、page-context 选择上行、ResultCard 同形渲染与诚实降级
paths: ["apps/merchant-admin/**/*"]
---

# 商户独立后台规范 (Merchant Admin)

`apps/merchant-admin` 是 v4 新增的独立商户后台(Vite 6 + React 19,端口 3006,`bun run dev:merchant-admin`;`/api/*` 由 Vite proxy 代理至 gateway-py 4000,`GATEWAY_URL` env 可覆写)。员工/老板工作台:全局悬浮数据分析助手 + RBAC 动态菜单 + 优惠/订单/商品/客户 CRUD。组件强制 workspace 包 `ui` + Tailwind,界面中文。

## 1. 核心架构与页面

### 1.1 路由与动态菜单

- `App.tsx`:未登录整树渲染 `LoginPage`;登录后 `AdminShell`。路由表固定 18 条(`/analytics` `/board` `/reports` `/orders` `/approvals` `/agent-desk` `/live-desk` `/promotions` `/ai-usage` `/customers` `/menus` `/roles` `/staff` `/owner-mappings` `/products` `/products/:code` `/skus` `/spi-logs`,`*` 兜底重定向 `/products`;orders/approvals/live-desk/spi-logs 四条共用 `OrderWorkbench` 按 scope 分域;2026-10-24 工作台收敛 + AI 用量入账)。侧边栏导航**不写死** —— 由 `GET /api/admin/analytics/menus` 下发的 `MenuNode` 树(directory/menu/button + `permCode`)驱动,`route` 字段对齐上述路由表;新增页面须同批补服务端种子菜单(`engine_py/analytics/rbac.py`),否则导航不可见。
- **身份 = Bearer JWT**(0013 收口,后端不再信任 `x-user-id` 头)。**transport 唯一收口(2026-10-15 候选②归一,此前 `req`「非 2xx 即 throw」与 `fetchJson`「返 body」两套语义并存)**:`api.ts` 的 `requestJson` 一条路径 —— ①401 清会话回登录(单点);②4xx/5xx 带 JSON body 原样返回,由页面按 `success`/`message` 呈现文案,不吞进 throw;③非 JSON 体/网络断诚实 throw(严禁裸 SyntaxError)。**失败文案一律 `errMsgOf(body)`**(message/detail/error 三键单点出口),严禁页面散写 `b.error || b.message` 式多读法。特例自留形状:`authedFetch`(ui 审批机注入面,不吞非 2xx)、`login`(唯一无会话端点,10s 超时 + 防枚举文案)、`api.ask`(SSE 流式走 authedFetch,ADR-0013)。会话行形状修补(id/threadId/lastMessage 互补)在 `api.conversations.list` adapter 收口,页面拿成品行。
- 老板身份切换:顶栏 select 仅 `hasBossSession()` 可见;`api.staffSwitch` 以留底的老板凭证(localStorage `merchant-admin.boss`,首次切换时保存)调 `POST /api/admin/analytics/staff/switch`,服务端为目标员工换签 JWT。`x-tenant-id` 硬编码 `'aurora'`(单租户 dev)。

### 1.2 悬浮数据分析助手 (FloatingAgent)

- 任意路由可唤起(挂 `AdminShell` 主区右下角);上下文 = 当前路由 + 列表页勾选。提问经 `POST /api/admin/analytics/ask`:fetch 流式读取 + `createFrameParser` 增量解析 SSE 帧逐帧回调。帧带自增 `id`,渲染层按 id 回写状态(按下标会错位);`start` 帧过滤不渲染。 **断线续传与恢复(2026-10-12 收口)**:ask 流本身已带续传(夜审 A6)——服务端 POST 收 `askId`+`lastEventId`(body/头双通道)只补 `seq>last` 不重算(生产者挂后台任务,客户端断开不停算;帧留 Redis 600s),`api.ask` 内建 3 次续传循环;本次补最终失败面:`AskStreamError`(api.ts)携带 askId/lastEventId/已收帧抛出,FloatingAgent 把部分帧照常上屏 + error 帧落恢复句柄,「恢复结果」按钮携句柄重进流(**不重算**;恢复成功/再失败都摘旧错误帧不堆按钮;流过期由服务端 error 帧诚实回「请重新提问」)。AskTranscript 渲染缝补 heartbeat 过滤(长问曾每 15s 渲染一条「heartbeat」气泡)。契约:`api.ask.test.ts`(4 例)+ FloatingAgent 断线三例 + ask-transcript heartbeat 例;服务端重放语义由 `test_analytics_ask_replay.py` 钉死。
- `pageContext = {route, selection, selectionLabels, sessionId}`;`sessionId` 浏览器侧稳定(localStorage `merchant-admin.session`),服务端 Redis 会话存储按此键维护多轮上下文。
- **Ask 会话单点(2026-10-15 架构收敛,CONTEXT.md「Ask 会话」)**:帧机(帧数组/自增 id/heartbeat·start 摄入期过滤/history 防抖落盘与卸载 flush)、AskStreamError 恢复句柄物化(error 帧 + 「恢复结果」不重算)、pageContext 组装(勾选上行 + 会话身份)、clarify 追问句组装、rated 反馈闩锁全数下沉 `lib/ask-session.ts` —— 悬浮面板 / analytics 全屏 / 看板重放三 surface 是其薄 adapter,**严禁在组件内自造并行帧类型或重抄组尾谓词**(`SessionFrame`/`isFeedbackTail`/`clarifyAskQuestion` 单点在此;帧→问句关联走 `SessionFrame.question` 标注,`__question` 私货通道已退役)。会话身份 = 多轮记忆开关:面板与全屏共享 `merchant-admin.session`(`currentAskSessionId`,面板「新对话」轮转、全屏随动);看板重放**刻意不带 sessionId**(重放=刷新,服务端双闸零读零写)且**刻意不接 resume**(resume 只取回 600s 内缓存旧帧,毁掉刷新目的),重放与手动刷新互斥(busy 闸)。测试桩若 mock `@/lib/api` **必须导出 `AskStreamError` 真类**(core 以 instanceof 判恢复句柄;mock 缺导出 = appendError 当场 TypeError、错误帧静默落不了),且桩须逐帧回调 onFrame(会话只消费 onFrame,返回值不兜底)。
- localStorage 键位约定:`merchant-admin.token`(JWT)/ `.staff`(当前员工 email)/ `.boss`(老板凭证留底)/ `.agent.history`(对话帧,上限 60)/ `.board`(钉看板 pin,上限 20)/ `.session`(agent 会话 id)。
- 事件面板:`user`/`pending`/`result`/`clarify`/`unsupported`/`error`;result 帧 = `ResultCard` + `summary` 速览 + 导出 CSV(BOM 头防 Excel 中文乱码)+ 📌 钉看板 + 存为报告(`reports/from-result` 服务端持久化,`saved` 标记防重复)。
- 答案反馈(反馈闭环 v3.1,2026-10-06):终局帧带 `traceId`(引擎盖章),**同 traceId 连续帧只在组尾**渲染共享组件 `FeedbackButtons`(result 双按钮;unsupported 仅 👎;error/clarify 不渲染);👎 先展开可选备注再提交;`rated` 标记随 `.agent.history` localStorage 持久化(闩锁,失败回滚 + 错误帧);`/analytics` 全屏页 `ask-transcript.tsx` 同款镜像(rated 随会话内存);看板/报告回放页刻意不评(回放生成新 askId,反馈语义不成立)。
- 就地唤起:任意页面 `window.dispatchEvent(new CustomEvent('merchant-admin:open-agent', {detail: {question}}))` 开面板并自动提问,不跳页。

### 1.3 page-context 选择上行(T5 契约)

- `lib/page-context.ts` 内存广播:`getSelection`/`setSelectionKind`/`toggleKindId`/`clearSelection`/`subscribe`。`kind ∈ 'order' | 'spu' | 'customer'`,ids 去重截断 ≤100;labels 并行存 `{kind: {id: 人话标签}}` 供图表标题等人话呈现。
- **严禁入 localStorage**:残留勾选曾两次静默污染查询(实弹踩坑),选择是一次性会话上下文,随页面会话生灭;旧键 `merchant-admin.selection` 在模块加载时一次性清除(迁移 2026-09-22)。
- FloatingAgent 订阅广播即时显示「已勾选 N 项」横幅,点击横幅即清除。

### 1.4 结果卡 ResultCard(同形渲染 + 诚实降级)

- 唯一结果渲染缝:悬浮面板 / analytics 全屏问答 / 看板重放 / 报告详情共用同一 `ResultCard` —— 改渲染行为只改这一处,四处自动一致。**信任章(ADR-0010,2026-10-07)**:result 帧 `trust` 字段(verified/composed/explored,机器语义)驱动 `TrustBadge` —— verified 零视觉噪音,composed 蓝章「组合查询」,explored 琥珀章「探索性结果」+ `generatedSql` 折叠展示(口径可审计);呈现层严禁解析口径文案推断信任级。
- 图形纪律(**诚实降级,绝不画假图**):
  - 折线:值列(行内第 2 列)必须全员 `Number.isFinite` 才画;数据点 <2 或值列非数值(如对比卡第 2 列是「品类」文案)出诚实说明卡 + 表格。实弹:历史持久化帧重放曾把 `Number('潮流T恤')` 画成三条 NaN 网线(2026-09-25 修复)。
  - 条形:`rankingPoints` 需 ≥2 行且末列数值,取前 10;`NO_BAR_METRICS`(`order_overview`/`customer_orders` 逐笔列表)永不画条;`chart='bar'` 用户指令但形状不符 → 诚实说明卡 + 表格。
  - `chart='table'` 尊重用户指令,不画图。
- 「折线仅趋势族」是**服务端**约定(`engine_py/analytics/graph.py` `_effective_chart`);前端数值护栏是历史帧重放/服务端回归时的最后防线,两层都不可拆。
- analytics 全屏问答页(`ask-transcript.tsx`)唯一例外是 `customer_orders` 的 `CustomerOrdersCard` —— 行级「在订单中查看」跳转是本页独有交互;其余 result 帧一律交 `ResultCard`,严禁自绘表格(2026-09-25 NaN 网线事故的自绘旁路已收口)。订单金额口径与订单管理页一致 `toFixed(2)`,缺值/坏值诚实「—」(`Number(null) === 0` 必须先挡,否则缺金额渲染成假 ¥0.00)。

### 1.5 看板页 (board)

- 钉看板 pin 存 localStorage(`.board` 上限 20):`{id, question, route, pinnedAt}`;每 60s(`REFRESH_MS`)对 pin 的问题重放 `api.ask` 刷新。重放走完整 ask 管线,`ResultCard` 渲染与悬浮面板同形。

### 1.6 优惠活动页 (promotions,2026-09-27 运营闭环)

- **生效态由服务端派生**:列表行的 `effectiveStatus`(disabled > ended > scheduled > running,与结算引擎窗口判定同口径)直显四态,前端严禁自行按 start/end 算;手工启停按钮仍走 `status`(active/disabled)开关,两者解耦。
- **新建/编辑 = 页级 `PromoFormDialog` 弹窗一表两态**(页头「+ 新建活动」或行内「编辑」唤起;类型卡片仅新建可选,编辑态类型不可改——PATCH 不携带 promoType)。PATCH 按「携带即更新」发全字段 —— `endAt: null` 置长期、`totalQuota: null` 清上限、`startAt` 传空保持原值(引擎 `update_promotion` 语义:区分「未传」与「传 null」);门槛仅满减携带,不把表单残留值写进库。弹窗内含客户端轻校验(名称/优惠数值必填、折扣 1-99、止 ≥ 起、上限正整数)与实时规则预览,提交失败在弹窗内呈现不关闭。
- 券型行显 `已领 X/上限 Y`(发放量控,服务端 claim 闸拒超发);发券面板头部显剩余可发;行内小字效果注记 `核销 N 单 · 让利 ¥X` 来自 `redemptionCount`/`discountTotal` 聚合。

---

## 2. 编码与维护准则

1. **数据操作收口 `lib/api.ts`**:页面只做编排,一切后端调用经 `api` 域对象(`menus`/`roles`/`staff`/`menuAdmin`/`customers`/`reports`/`products`/`promotions`/`ask`);新增后端接口同批在此加方法与 TS 类型,严禁页面裸 fetch。
2. **SSE 帧解析只经 `lib/sse.ts`**(`parseSseFrames` 全量 / `createFrameParser` 增量),与网关 `_sse()` 帧格式一一对应;坏 JSON 跳帧不中断流。
3. **RBAC 前端只做可见性**:菜单树由服务端下发,权限判定真源在服务端 `permCode`;严禁在前端复制权限表。**信任边界如实(2026-10-15 安全审计 #3)**:前端路由守卫(`lib/route-guard.ts`)拦截的是页面骨架;读数据端点的服务端 permCode 收敛**尚未覆盖**(现仅身份+租户闸,低权限角色直打网关可得本租全量数据),文档与注释严禁宣称「服务端已兜底数据」——permCode 装饰器收口前列为待办。
4. **测试**:`cd apps/merchant-admin && bun run test`(vitest,249 例/42 文件,与被测文件同目录就近放置;`src/test/live-api.ts` 可起 live 网关做集成);Playwright E2E `e2e/merchant-admin.config.ts`(testDir `apps/merchant-admin/e2e`,复用运行中的 3006 前端 + 4000 网关;dev 种子账号 `test@example.com` 老板 / `ops@aurora` 运营 / `wh@aurora` 仓储,密码统一 `agent-all-dev`)。
5. **中文界面 + workspace 包 `ui` 原子组件 + Tailwind**:与 web/admin 同一零依赖 UI 不变量,严禁引入重型外部组件框架。**全控件 shadcn 化(2026-10-09 用户裁决)**:表单/表格/按钮一律用 `ui`(= packages/ui,shadcn 项目)的 `Input`/`Label`/`Select` 全家/`Checkbox`/`Table` 全家/`Button`/`Dialog` 全家,严禁手写原生 `<input>/<select>/<table>/<button>/<label>`。要点:
   - **Radix Select 空值两律**:`SelectItem` 的 value 禁空串(Radix 抛错)。不可选占位(「— 选择负责人 —」)→ Root 受控 `value=''` + `<SelectValue placeholder>`;真·可选空值(「未分配/未定级」)→ **一律用本地 `src/components/optional-select.tsx`**(2026-10-15 候选③:哨兵生命周期封进组件,onChange 直收 '',哨兵物理上进不了 payload;此前 4 文件 6 站点自持 `__unset__` 常量、映射贴在写库边界,写漏一次哨兵即入库),严禁组件内再自写哨兵映射。
   - **表格密度**:ui Table 默认 h-12/p-4 过松,统一用本地 `src/components/dense-table.tsx`(px-4 py-2 / 13px);条件色/选中态类经 className 透传仍后者胜。**ResultCard 三张内嵌表为显式豁免**(四处共用渲染缝,见其文件头注释)。**单元格/表头禁折行(2026-10-18 用户裁决)**:dense-table 单点预设 `whitespace-nowrap`,中文竖排折行(「满/减」「进行/中」)一律靠横向滚动(ui Table 自带 overflow-auto 包裹)消化;真需折行的长文本列(订单收货地址 line-clamp-2)由 caller 显式 `whitespace-normal` 解除。视觉契约 e2e `e2e/ui-contract.e2e.ts` 钉面。
   - **主题覆盖**:`src/styles/theme.css`(main.tsx 中在 ui globals 之后引入)把 shadcn token 覆写回站点 zinc(`--primary`=zinc-900 / `--ring`=zinc-400)——语义类(bg-primary/ring/checked)随之贴站,勿在组件上散写蓝色覆盖。**禁写 `dark:` 变体**(2026-10-10 实弹):Tailwind v4 的 `dark:` 默认 = `prefers-color-scheme` 媒体查询,OS 深色下散写半边翻色 → 黑底黑字;结构性闸在 ui globals.css 的 `@custom-variant dark`(类驱动,无 `.dark` 类恒惰性),源码面由 `src/light-theme-contract.test.ts` 钉零容忍。
   - **登录失败面诚实降级**:`api.login` 带 10s 超时,5xx/超时/不可达各自诚实文案(proxy 500 非 JSON 体曾漏裸 SyntaxError、挂起曾永久「登录中…」);401 仍返回 body 走「邮箱或密码错误」防枚举统一文案,勿在 login 里吞 401。
   - **jsdom 单测驱动 Radix**:`src/test/setup.ts` 补 `hasPointerCapture`/`releasePointerCapture`/`scrollIntoView`/`ResizeObserver` 四桩;选择交互走 `src/test/radix-select.ts` 的 `selectRadixOption`(Radix Select)/ `selectComboboxOption`(SearchableSelect)。E2E 侧:click trigger → `getByRole('option')` click;trigger 回显断言用 `toHaveText`(button 无 value);弹窗内下拉**禁用 Esc 收层**(Esc 会连坐关 Dialog),改外点切下一控件。
   - **长列表可搜索**:本地 `src/components/searchable-select.tsx`(Popover+Command 组合,shadcn combobox 官方范式;空值不回落首项)用于 20+ 项下拉(商品/指标维度值);短列表仍用 ui Select。ui 的 `Combobox` 是 admin 租户选择器特化(写死 ID 副标题),勿复用。
   - **新增/编辑一律弹窗**(2026-10-09 用户裁决):全站内联新增/编辑面板已收敛为 Dialog(促销新建+编辑/客户/商品(新增+行内编辑)/SKU 子表改价与新增/库存页改价/菜单/角色新建+分配权限/员工邀请/责任人登记/核销/发券)。范式:页面头「+ 动作」Button → 页面级 dialog state → 组件 `XxxDialog`(props 用 `onClose`,成功 onMsg+onClose,页面 onClose 时 reload);弹窗 chrome 统一 `rounded-xl border-zinc-200 p-6 text-zinc-900 shadow-xl` —— **p-6 必须由壳/消费方自给**(ui 包 `DialogContent` 本体不带 padding,apps/admin ConfirmDialog 同律;32ea113 收口抄丢 p-6 曾致 13 弹窗内容贴边,FormDialogShell 单测与 ui-contract e2e 双钉)。工具型小输入(搜索/回复/备注/驳回理由)保留内联。
