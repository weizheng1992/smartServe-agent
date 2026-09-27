# 客服工作台重构 spec (live-desk-rework)

> 状态:**spec 定稿(2026-09-28),待执行立项**。产出自 wayfinder 本地图
> (`.scratch/live-desk-rework/`,本地工作档案不入库;15 张决策工单为本文档的推理底稿)。
> 范围铁律:merchant-admin 坐席面 + gateway/engine 后端;apps/web 仅边界说明(§7)。

## 1. 结论

**重构,以「丙·混合」为基座**:AI 作业流保持 SSE 不动(Redis Streams 事件源 + Last-Event-ID 回放是冻结契约);坐席协作面接入**既有 socket.io 层**(6 事件线格式已冻结、11 例契约、JWT 身份绑定已收口);动作语义(审批批驳等)留 HTTP POST。顾客面(apps/web)**零强制改动**,留轮询,预留 `role=user` 推送位放后期。

现状四能力(会话分配/坐席上下文/消息可靠性/审批联动)**全部为零**,且有三处**事故级**缺口,不是「功能少」而是「在出事故」:

1. **接管不可释放、掉线永久卡死**——测试钉死「断开≠release」,坐席断线后会话卡在接管态,只能 DB 手工改;
2. **AI 无暂停闸**——socket 宣称「AI 已暂停托管」但代码不强制,接管期 AI 照答,双声部打架;
3. **审批面曾匿名可批**——已由安全先行收口(第 0 期,提交 `1317d43` + `91348c9`)。

真实接管链是 HTTP 轮询 + `"[人工客服] "` 字符串前缀识别 + 两台互不相通的状态机(socket 写 `threads.status`,HTTP 走 approval 工单不改 threads 列)。

## 2. 目标架构

### 2.1 接管状态机:单一真源(零迁移)

- 真源 = **`threads.status` + `assigned_operator_id` 列**,HTTP 链与 socket 链同写。复合语义:`human_takeover` 且坐席空 = **呼叫中/排队**;非空 = **接管中**。不新增状态值。
- 工单退化为**审计记录**(顾客呼叫凭证与时效),状态机照旧,与 threads 活态解耦。
- **AI 暂停闸 = 网关入队前**:`POST /api/chat` 建作业前读真源,接管期该会话全部轮次不建作业不调 LLM,用户消息照常落库;`release` 回 `active` 后下一条自然走 AI。入口单点(顾客消息仅 chat 入队一条路)即全覆盖。
- **断线与释放**:工作台补释放按钮;掉线**不立即回退**(防抖动误伤),超时(60~120s 可配)未重连自动释放 + system 消息告知,重连取消。**权威路径 = DB deadline + scheduler 幂等条件 UPDATE 扫描**(与排队超时回落共用扫描回路,两个超时一个 worker);进程内计时器只可作 UX 快路径提示,不可作唯一路径(多实例约束,见 §6 引)。
- **坐席消息标识 = `role='operator'` + `operator_info` JSONB**(列已存在零迁移);`"[人工客服] "` 前缀拼接退役,老数据前缀解析保留为只读兼容 fallback,不做历史回填。

### 2.2 坐席身份与权限(零迁移)

- 新增 **`support_agent` 角色**:默认授予客服工作台 + 客户管理,**不给**数据分析/订单/商品/优惠/系统面(商户可招专职客服不泄经营数据);finance_owner/admin 全量。
- 权限面 = 菜单可见 + 两个按钮点:`live_desk:operate`(接管/发言/释放,坐席持)、`live_desk:approve`(工单批驳,坐席默认不持,留老板/管理员);API 逐路闸照 `order:ship` 的 `perms_for_role` 先例。
- actor 真源 = staff 表(`display_name` 唯一显示名)+ 消息级 `operator_info` 快照(改名不篡改历史);`assigned_operator_id` 存 email 不冗余名。**不引入 store 维度**(business_id 即租户边界,02 双闸已守)。

### 2.3 会话分配与队列(零迁移)

- **自选认领池**:队列 = `human_takeover` 且坐席空,列表**等待最久置顶**;认领 = socket `takeover_conversation` + 服务端**原子守卫** `UPDATE threads SET assigned_operator_id=:op … WHERE assigned_operator_id IS NULL`(两坐席同抢只成一人);自动派单/转接明确不做。
- **在线态 = 连接态即在线 + 手动免打扰**:presence 存 **Redis(TTL 心跳)** 共享存储;仅展示不作分配闸;在线态(人的能力态)与接管态(会话级)严格分层。
- **排队超时回落 AI**(默认 ≈5min 可配):无人认领自动回 `active` + system 告知顾客,AI 暂停闸随状态自然解除;扫描走 **DB 时间戳 + `engine_py.scheduler`**。
- **未读 = 激活存量 `unread_count` 死列**(顾客消息落库 +1,坐席打开时间线清零,仅坐席台展示);排队时长取 `threads.metadata.takeover_requested_at`。

### 2.4 坐席上下文(唯一 DDL:thread_notes)

- 最小闭环五项:客户档案 / 最近订单 ≤5 / 售后中工单 / 双层画像摘要(**global|tenant 分栏**,租户隔离不变量照旧)/ 内部备注。历史 LLM 摘要明确不做。
- **备注存 `agent_merchant` 库 `thread_notes` 表**(幂等 DDL,promotions 同模式)——顾客链路物理触不到该库,「不外发」靠构造不靠纪律(前车之鉴:`list_user_threads` 全量回显 `threads.metadata`)。
- 供给 = **一次性聚合端点** `GET /api/merchant/live-desk/threads/{id}/context`:单次往返零扇出,员工闸 + `live_desk:operate`,租户从 staff 行带;实施期首项核实 chat `userId` ↔ `merchant_orders.customer_id` 关联键,弱关联如实标注「未匹配」不编造。
- 交互形态已定(IA 原型):右栏 w-80 **堆叠不 Tab**,可折叠。

### 2.5 信息架构(IA 原型定稿)

三栏布局(工件:`.scratch/live-desk-rework/assets/ia-live-desk.md`):

- **左 · 会话列表 w-72**:筛选(全部/排队中/我的)+ 搜索;排队行 = 等待最久置顶 + 计时 + [认领] 按钮;未读角标吃 `unread_count`。
- **中 · 时间线 flex-1**:顶部**常驻接管状态条**(AI 托管 / 排队中计时 / 我接管中 / 同事接管中),**释放按钮在状态条内**(释放语义=对当前会话;列表行只放认领),掉线倒计时小字提示;消息流 role=user/operator/system 分形渲染;工单卡内嵌时间线(system 行引导定位),无 approve 权限呈只读 + 转办提示;输入区含乐观气泡、typing 指示、快捷短语。
- **右 · 上下文栏 w-80**:五项堆叠可折叠。
- **四域解耦**:新 `pages/live-desk/use-live-desk.ts` 独立 hook;`useWorkbenchState`(456 行)删 conversations 域,8s 单轮询不再拉会话;共用 `useApprovalMachine`(ui 包)与驳回弹窗;类型升 `lib/api.ts`;`approvals-tab` 留工作台兜底,旧 `live-desk-tab.tsx` 退役。
- 雾区裁决:`/conversations` 只读浏览器(apps/admin)**保留不改造**(平台侧全租户审计浏览器);`useAdminDashboardData`+`startActiveTakeover` **退役**(hooks barrel 零消费方死代码;apps/web 同名函数是顾客呼叫人工活路径,不动)。

### 2.6 审批工单联动

- **台内一等 + 管控台兜底**:会话内嵌工单卡批驳,走 02 员工代行路径(`/api/chat/approvals` 带 JWT,对象级租户校验已在),闸 `live_desk:approve`;管控台 approvals 页保持全局兜底,两通道同语义不同视角,不建第三通道。
- **消息与工单显式解耦**:发消息 = socket `send_message` 纯发言,与工单无隐式关联(现状「普通聊天被偷换为工单回复」bug 消灭);`human_reply`/`human_finish` 动作退役(白名单移除 → 400「未知审批动作」)。
- **批驳后不自动释放**:工单终局只落审计 + system 消息,会话保持接管直至显式释放/掉线超时;审计直接消费 02 契约(`resolvedBy`/customer 语义)零新增。

### 2.7 消息可靠性

- **幂等**:客户端为每条外发消息生成 UUID 作 clientMsgId(兼作乐观气泡 key),`send_message` handler 透传 → `messages.id`(地基已在:`INSERT … ON CONFLICT (id) DO NOTHING`);重复投递静默不落,ack 回既有 messageId;重复 `new_message` 广播由前端按 id 去重。零迁移。
- **回滚**:乐观气泡的回滚依据 = `ack.success === false` 或 ack 超时(10s 兜底)→ 移除气泡 + 错误提示。
- **typing**:服务端零新增(`user_typing` + skip_sid 防回声已完备且契约已钉),纯前端接线。
- **流式回放补发不做**:重连成功回调触发一次 `loadHistory` 兜底刷新(简单最终一致);兜底不够再议。

## 3. 分期方案(渐进式:每期独立可用、可回退)

第 0 期(安全先行)已完成:`1317d43`(POST 分面收口/socket JWT 绑定/rbac 按钮点)+ `91348c9`(GET 员工面收窄/跨租户 403/匿名过渡语义钉死)。

| 期 | 范围 | 验收 | 回退 |
|---|---|---|---|
| **P1 真源归一+事故止血** | threads 真源 HTTP 链双写;AI 暂停闸(入队前);释放按钮(现工作台先加);掉线超时释放(DB deadline+scheduler 扫描权威,计时器提示);坐席消息写侧落 `role='operator'+operator_info`(读侧前缀兼容保留) | pytest:双写一致性/暂停闸(接管期不建作业、release 后恢复)/超时释放幂等扫描/operator 落列;**新增首条 Playwright「接管→释放→AI 恢复作答」(事故回绿钉)** | 双写开关,旧链路行为不变 |
| **P2 分配与坐席台独立页** | `pages/live-desk` 三栏;认领池+原子 UPDATE;队列等待最久置顶;presence TTL+免打扰;`unread_count` 激活;排队超时回落扫描;support_agent 角色+operate perms | pytest:认领并发(双请求一成一败)/presence/回落扫描幂等/perms 三态;vitest:列表排序/认领/状态条;Playwright:坐席↔顾客 socket 往返 | 旧 tab 并存,回退=菜单下线新页 |
| **P3 坐席上下文栏** | 聚合端点;`thread_notes` 幂等 DDL(本期唯一 DDL);右栏五项 | pytest:鉴权矩阵(匿名 401/跨租户 403/员工 200)/五项形状/notes 幂等+隔离+不出现在任何顾客响应;vitest:五项渲染+诚实空态 | 右栏默认折叠 |
| **P4 工单联动+消息可靠性** | 工单卡内嵌批驳;消息工单解耦(`human_reply/human_finish` 退役);clientMsgId 幂等+乐观回滚+typing | pytest:批驳走员工通道/批驳后不自动释放/clientMsgId 重放同 id/typing 接线/退役动作 400;Playwright:ack 失败回滚 | 工单卡退化为只读+工作台兜底链接;幂等纯加法 |
| **P5 退役与收口** | apps/web 接线+匿名 GET 硬切 401+属主过滤(翻转 `91348c9` 钉死的过渡语义);轮询两步撤梯降 30s 兜底;admin 死代码删除;前缀读侧兼容清除;契约迁移清单销账 | pytest:**翻转**匿名 GET→401、属主过滤;退役项 grep/import 断言入 CI;e2e:顾客轮询链(30s 兜底)不断 | 保留 30s 轮询兜底即永久降级路径 |

事故级三缺口(释放/掉线卡死/AI 暂停闸)**并入 P1 不独立成期**:「释放」的语义就是写真源,绕开归一在双状态机上补释放=一次性丢弃工作;P1 只做 HTTP 双写让释放按钮立刻可用,不等传输迁移。

**灰度开关 = RBAC 菜单可见性,零新 env**:服务端种子菜单树即发布闸——新页先只授老板/管理员,稳后放 support_agent;回退=菜单下线,旧 tab 保留至 P5 才删。

## 4. 契约迁移策略

「契约先行」落点 = 每处改动同批 pytest;39 条 TS 基线 HTTP 路由、SSE 帧形不碰。逐项:

| 处置 | 项 | 同批契约 |
|---|---|---|
| 退役 | `[人工客服] ` 前缀识别(写侧 P2,读侧 P5) | operator 落列 + 老数据 fallback 渲染 |
| 退役 | `human_reply`/`human_finish` 动作(P4) | 白名单移除 → 400「未知审批动作」 |
| 已退役 | x-role 自报头 / 匿名 actor(第 0 期);GET 匿名放行(P5 翻转) | 翻转 `TestGetListStaffFace` 过渡语义例 |
| 冻结 | SSE AI 作业流帧形;socket 6 事件**形状**(joined_room/peer_joined/conversation_state_changed/new_message/user_typing/peer_disconnected) | 载荷扩展同批 pytest;形状变更按退役级对待 |
| 新增载荷 | `send_message` 收 clientMsgId → `messages.id`;ack 失败分支(`success:false+error`) | 幂等重放同 id / 回滚触发 |
| 新增载荷 | `conversation_state_changed` 统一为 threads 真源形状(status/assignedOperatorId/unreadCount) | 真源变更的线格式出口 |
| 新增路由 | `GET /api/merchant/live-desk/threads/{id}/context`(冻结面外,按规则同批 pytest) | 鉴权矩阵 + 五项形状 + 租户隔离 |
| 显式不加 | 顾客面推送事件;排队池/未读的房间级广播新事件;服务端 typing 改动 | 顾客面留轮询;队列变更由降频轮询兜底覆盖(少一个跨实例广播点) |

## 5. 测试补齐清单(现状缺口 → 目标)

- 现状无 live-desk e2e、无轮询链路测试。每期门槛统一:**双服务 ruff + pytest 全量绿 + merchant-admin vitest 绿**;e2e 只测跨端往返(P1 起逐期累积,见 §3 验收列)。
- pytest 行为钉点:暂停闸、超时释放幂等扫描(重复扫描 0 行)、认领并发负例、presence TTL、排队回落、聚合端点鉴权、notes 隔离、批驳不自动释放、clientMsgId 幂等、退役动作 400。
- Playwright(新增,P1 首条):接管→释放→AI 恢复(事故回绿钉)→ P2 双端消息往返 → P4 ack 失败回滚 → P5 顾客轮询链不断。

## 6. 多实例兼容结论(引 docs/architecture/multi-instance-deployment.md §6)

四能力数据决策全部落共享存储,无新增进程内存态单点,「真源归一」整体**降低**单实例债。`connected_clients` 结构性安全(handler 永跑在连接属主进程);唯一须守住的约束:**掉线释放的权威路径必须是 DB deadline + scheduler 幂等扫描,进程内计时器仅 UX 提示**(P1 已按此落);坐席面迁 socket 的扩容前提 = 按 §3.2 配 `AsyncRedisManager`(既有方案,本期不实施)。

## 7. 域边界与交接

- **apps/web:零强制推送接入**;唯一牵连 = 退役项配合(坐席消息渲染语义、AuditDesk 401 呈现、GET 审批列表鉴权接线)+ `client-web.md` 失真修正——已立执行票 `.scratch/live-desk-rework/issues/14-web-touch-list.md`,归 **P5 同批**,本 spec 不展开。
- **Out of scope(重申)**:apps/web 整体重构;socket.io 跨实例广播的实施;AI 决策管线自身重构(暂停闸除外);快捷回复/常用语内容管理(效率工具,分期有余量再议);自动派单与转接。
- **交接**:本地图关闭后按 spec 立项执行,期序即 §3;每期开工前回读本节验收列与 docs/architecture/multi-instance-deployment.md §6。
