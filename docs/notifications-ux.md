# 商城站内消息推送 · 顾客侧显示与链路(mall-notifications)

> 状态:as-built(2026-11-02,随 65019283 + d9529e1e + d9627226 落地)
> 决议与验收全账:`.scratch/mall-notifications/prd.md`(D1-D13)与 `issues/01-06`(本地 issue tracker,不入库)
> 本文回答一个问题:**顾客在商城(3005)看到的推送是什么、从哪来、怎么变已读。**

## 1. 一图流

```
注册顾客(CUST-*)打开商城 3005
│
├─ 顶栏「🔔 消息」(navLinks 同款;游客与非顾客身份不渲染)
│    徽标数字 = GET /api/store/notifications/unread-count
│    刷新时机 ×4:进页 / 回前台(visibilitychange)/ SSE 信号帧 /
│      notify_updated 窗口事件(消息中心标已读时广播)
│         ↑ 信号流 notifyStreamConnection(自管 EventSource,退避 1s→30s;
│           帧只当信号不载数据,他客定向帧在 isSignalForMe 丢弃)
│
└─ 点入 /messages 消息中心
     ├─ 列表:20 条/页,时间倒序;未读行 = 绿点 + 加粗标题 + emerald 描边
     ├─ 点开行 = 展开正文 + 单条标已读(POST /read)→ 徽标即时消减
     ├─ 「全部标为已读」(有消息即恒驻,不随本页未读隐藏)
     └─ 空态/游客 = 「暂无消息」;缺值诚实(时间/正文缺失显「—」)

数据真源恒为拉取端点;SSE 断线只降实时性不丢数据,重连成功即重拉自愈。
```

## 2. 铃铛(`NotifyBell.tsx`)

- **可见性**:`user.id.startsWith('CUST-')` 才渲染——游客(guest-\*)与任意非顾客身份零接入:无铃铛、无入口、不建 SSE 连接(U2 律,prd D4)。
- **未读数真源**:`GET /api/store/notifications/unread-count`(服务端 anti-join 已读表),前端从不本地推算。
- **四个刷新源**:挂载、`visibilitychange` 回前台、SSE 信号帧、`notify_updated` 窗口事件(消息中心标已读后派发,与购物车 `cart_updated` 同款先例)。
- **样式**:顶栏 navLinks 同款胶囊;`/messages` 激活态反色;徽标 >99 显示 `99+`。

## 3. 消息中心(`/messages`,`MessagesPage.tsx`)

- **列表**:20 条/页,`created_at` 倒序,行含标题/时间/已读态;未读行有行首绿点 + 加粗标题 + emerald 描边。
- **点开行** = 展开正文 + 单条 `POST /read` 标已读(幂等,重复点不重复计)。
- **「全部标为已读」**:有消息(`total > 0`)即恒驻——复审 P6 裁决:未读只在后续页时入口仍须可达;按钮可见性因此**不是**已读态信号,已读态看行内绿点与页头「本页未读 N 条」计数。
- **诚实呈现**(merchant.md 数据诚实律):正文可留空(发送侧不强求),空正文展开显「—」;时间经 `fmtDate` 解析,缺失/坏值「—」。
- **空态**:「暂无消息 · 商户发布的新公告会出现在这里」——游客直达同此空态,不报错不特判。

## 4. 实时信号流(`notifyStreamConnection.ts`)

- **端点**:`GET /api/store/notifications/stream`(SSE;userId 必报 400,非 CUST-\* 400 拒连——无消息入口的身份不养连接)。
- **频道拓扑**:单频道 `notify:business:{businessId}` fan-in——广播帧无 `targetUserId` 人人有份;定向帧携 `targetUserId`,**连接侧过滤**(`isSignalForMe`),非本人帧不上抛。服务端不做 per-connection 过滤(那要复制 tail_pubsub 泵或改公共语义,均不值;帧零消息内容)。
- **帧语义 = 信号非数据**:收到即重拉未读数/列表,数据真源恒为拉取端点。
- **断线语义**:显式指数退避重建(1s→30s,同 chat 流 P7 律);**无水位回传**——通知流无 DB 时间线回放,断线窗口丢信号不丢数据;重连成功(`onopen` 且非首连)触发一次重拉自愈。
- **纪律**:自管帧流,严禁并入 `api.ts`(merchant.md §1 SSE 例外清单两成员之一)。

## 5. 端点与数据(速查)

| 端点 | 侧 | 用途 |
|---|---|---|
| `POST /api/admin/notifications` | 员工 | 发送(广播/定向;单员工单日广播 ≤20 常量闸) |
| `GET /api/admin/notifications` | 员工 | 已发历史(无已读回执字段,D6) |
| `GET /api/store/notifications` | 顾客 | 我的消息分页(含 isRead) |
| `GET /api/store/notifications/unread-count` | 顾客 | 未读数(徽标真源) |
| `POST /api/store/notifications/read` | 顾客 | 标已读(`{ids}` / `{all:true}`,幂等) |
| `GET /api/store/notifications/stream` | 顾客 | SSE 信号流 |

数据落 `agent_merchant.merchant_notifications` + `merchant_notification_reads`(广播不 fan-out,未读 = anti-join;DDL 随 `merchant_db.py` 启动自愈)。RBAC:菜单 `m-notifications`(d-ops)+ perm `notify:send`(support_agent 显式授,warehouse_operator 无)。

## 6. 本地查看

- **dev 网关(4000)重启前**,3005 打推送接口 404 属预期(旧代码在跑)。重启后全链可用。
- **不碰 dev 面的完整演示**:
  `bunx playwright test --config apps/merchant/e2e/notifications.config.ts --headed`
  自起 3007 私有 vite(GATEWAY_URL → 4100 私有网关,scheduler 关),跑完「发广播 → 铃铛 +1 → 点开 → 已读 → 徽标消减 + 游客零接入」两册;幂等可连跑(标题时间戳化 + 跑前 store 端点清零未读)。

## 7. 文件索引

| 文件 | 角色 |
|---|---|
| `apps/merchant/src/components/notifications/NotifyBell.tsx` | 铃铛 + 未读徽标 |
| `apps/merchant/src/components/notifications/notifyStreamConnection.ts` | SSE 信号流连接机(+8 例单测) |
| `apps/merchant/src/pages/MessagesPage.tsx` | 消息中心页 |
| `apps/merchant-admin/src/pages/notifications/` | 员工侧模块页(撰写弹窗 + 历史表) |
| `services/gateway-py/src/gateway_py/routers/merchant_notifications.py` | 六端点(+契约册 14 例) |
| `apps/merchant/e2e/notifications.{e2e,config}.ts` | e2e 册(私有 3007→4100 拓扑) |
