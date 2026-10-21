# apps/merchant 规则(独立商户门户,端口 3005)

顾客侧商城 SPA:陈列/购物车/下单/订单/自助身份 + 悬浮 AI 客服。与 merchant-admin(3006,员工后台)、web(3000,客户端聊天)三面互斥共生。本文件为 2026-10-17 双轴 code-review 后立约,此前本 app 无成文规约。

## 1. 单点模块(严禁绕行)

1. **传输唯一收口 `src/lib/api.ts`**(2026-10-17 收口,对齐 merchant-admin 候选②同型):一切 HTTP 经 `requestJson`/`postJson`/`uploadJson`/`auth.*`;语义三态 —— ①业务/HTTP 错误体原样返回由页面按 `success`/`errMsgOf` 呈现,不吞进 throw;②网络断原样上抛;③非 JSON 应答 `ApiError` 诚实上抛(网关挂时 vite proxy 的 HTML 500 严禁解析出 undefined 静默走成功)。**无 401 清会话臂**:store 面以显式 `userId`/`businessId` 自报身份(guest-\* / CUST-\*),员工 JWT 401 收口单点在 `apps/merchant-admin/src/lib/api.ts`。**SSE 例外**:`src/components/chat/storeStreamConnection.ts` 自管帧流(P7 退避 + ADR-0013① 重连补投),严禁并入 api.ts。裸 fetch 禁令:`src/` 内 `fetch(` 只允许出现于 api.ts 与 storeStreamConnection.ts(`grep -rn "fetch(" src/` 审计)。
2. **购物车单一形状所有者 `src/lib/storeCart.ts`**:读写一律走本模块(2026-09-14 NaN 事故收口);聊天快照合并走 `mergeCartSnapshot`(覆盖不累加 + 多键对账);`stock: null` = 库存未知,**严禁编造兜底值**。
3. **租户标识单点 `src/lib/tenant.ts`**:`MERCHANT_ID`(VITE_MERCHANT_ID,缺省 aurora)+ 线程/消息缓存键助手。**`aurora_` 存储键前缀是历史存档命名空间,刻意不收编**(改名即弃用户本地数据)。
4. **承运商译名 `src/lib/logistics.ts`**:`carrierLabel`(SF/JD/ZTO/EMS,未知编码原样透传)。**严禁编造承运商缺省**(无轨迹 → 「承运商待确认」,缺值 → 「—」)。
5. **身份语义 `src/context/UserContext.tsx`**:U2 游客律 —— 匿名访客 = 浏览器级 `guest-*`,与 CUST-\* 真客隔断;**任何路径严禁回落预设真实客户**(PRESET_USERS 仅显式切换的演示通道);注册缺失字段诚实空串,不编造。

## 2. 数据诚实律(与全仓同律,违例 = 硬伤)

- 缺值诚实呈现:缺价 → 「价格待确认」(CartPage `hasPrice` 闸,严禁 `|| 899` 类假价绕过);缺图 → 🛍️ 占位条件渲染(CartPage:326 house 先例,**严禁 unsplash 假图兜底**);缺承运商/收件人/状态 → 「承运商待确认」/「—」。
- 用户可见文案严禁携带未证实事实(「实时顺丰物流」类载体断言禁止;「顺丰特快运费」类运费政策文案豁免)。
- 死页契约:`/admin` 只出员工鉴权引导卡(`e2e/merchantConsoleAudit.e2e.ts` 钉死「不渲染业务数据与 Tab」);管理面归宿 = merchant-admin(3006);商品价格/库存编辑(spec Story 9)移交案见 `.scratch/open-merchant-integration/issues/07-story9-handover.md`。

## 3. UI 纪律

- 全控件 workspace 包 `ui`(shadcn 项目)+ Tailwind,严禁手写原生控件(CLAUDE.md §3.5 同族);Radix Select 空值两律与 merchant-admin 同款。
- 聊天卡片动作分发走 `CARD_ACTION_STRATEGIES` 表键集类型化(`CardActionName` 编译期穷举,未登记动作返回 null 由调用方兜底,不猜)。

## 4. 测试

- vitest 与被测文件同目录(`bun run test`);Playwright e2e 六册(`e2e/`,复用运行中的 3005 + 4000;跨册身份注入走 `addInitScript` **参数字面量,严禁引用 Node 闭包常量**)。
- 宿主 env 须 `AI_QUOTA_GATE=0`(用量配额闸,2026-10-21;`.env.example` 已缺省关):闸开时 e2e 复用 profile 的 guest-* 会撞游客终身 10 次、CI 绿锚慢性翻红。
- e2e 已钉契约:游客/顾客身份隔断(chatCartStorefront)、订单状态文案(merchantApp:75「待发货」)、/admin 引导卡与 401 闸(merchantConsoleAudit)。
