---
id: "005"
title: 图片治理与全链路验收
map: multimodal-image-chat
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: "weizheng"
status: closed
blocked-by: ["002", "003", "004"]
blocks: []
created: 2026-09-08
---

## Question

收口票:治理补齐 + 全链路验收,多模态链路从"能跑"到"敢用"。

**治理**(TS 时代零防护,考古裁决必须补):

- 引擎侧 imageUrls 归一化与校验:数量上限(如 ≤3/条)、坏 URL/不可达图不炸主链路(vision 失败=无 vision,不失败会话)。
- 上传与 vision 的双重限额对齐(网关 10MB/张 + 引擎总量)。

**验收**:

- E2E:选图上传 → 发破损图 → damage_assessment 卡片渲染(web 主链路 chromium)。
- `eval/testCases/ecommerce/multimodal-damage.json` 复核:现用例是 `[image: ...]` 文本模拟,裁决是否升级为真实图片链路用例(动基线须重钉并记录)。
- 文档回填:CHANGELOG、`docs/architecture/multimodal-and-rich-cards.md` 的 TS 残留引用、CLAUDE.md Phase 1b 回收池条目(多模态 vision 移除出池)。

**验收**:E2E 绿;契约/eval/prompt 基线不回归(或重钉有记录);ruff 干净。

## Resolution

**治理(归一化 + E2E 实测三修 + 用户行单写)**

1. `normalize_image_urls` 收口(剔非字符串/空白、去重保序、**≤3 图/条**截断),挂 `run_agent` 初始状态构建;与网关 10MB/张对齐;垃圾输入只少图不抛错。
2. E2E 实测三修:①`AI_VISION_TIMEOUT_SECONDS` 默认 15→30s(GLM-4.6V 真实请求可超 15s,超时降级即丢定责);②启发式破损词表补 `断裂|开胶|脱胶`(「鞋底开胶断裂」原全不命中,降级后连兜底定责都丢);③`_uploads_dir()` 默认 `parents[4]`→`parents[5]`(原解析到不存在的 services/public/uploads,本地图全被跳过;补 `test_default_uploads_dir_matches_gateway_layout` 钉默认分支)。
3. **用户消息双插治理**(E2E 诊断中发现的移植引入 bug):TS 树无 `appendMessage`,网关侧插入系移植新增,引擎又保留 TS 盲插 → 每条消息时间线 user×2(一行带图一行不带)。裁决:**用户行唯一写入方=网关**(dispatch/SPI,imageUrls 只在入口可得),引擎三处拔除(run_agent 主链/问候旁路/Temporal activity),assistant 行仍归引擎;`test_user_message_single_write.py` 两用例钉死所有权边界。

**E2E 验收**:`chat-multimodal-damage.e2e.ts`(chromium)绿,48.7s 全链——选图上传→真实 GLM-4.6V 定责(severe / 0.95 /「鞋底开胶断裂，完全不能穿」)→damage_assessment 卡渲染→刷新 `?threadId=` 自愈还原图与卡;单条 user 行带 imageUrls(双插已绝)。期间实证:上游 bigmodel 深度限流时链路可拖至 16 分钟(隔夜自愈),vision 超时降级启发式(0.88)仍出卡——双通道容灾按设计工作。

**eval 裁决**:`multimodal-damage.json` 维持 `[image: ...]` 文本模拟基线不升级——promptfoo 供给方是文本 LLM 无图片输入位;真实图片链路由 vision 单测 + E2E 覆盖;基线零改动零重钉。

**文档回填**:CHANGELOG 2.5.0(如实,含限流实证与存量缺口记录);`multimodal-and-rich-cards.md` TS 残留清账 + §2.2 入图治理 + §5.1 网关唯一写入方;`agent-engine.md` §1.3 入图治理条目 + §1.4 消息写所有权。CLAUDE.md Phase 1b 回收池条目:盘点核实 CLAUDE.md/docs/README 均无该条目(仅存于本图 Out of scope),无需动作。

**顺带记录(存量,不修)**:①侧栏历史列表依赖 `GET /api/chat/threads`,网关仅实现 POST/DELETE 返 405,刷新后列表恒空(当前线程靠 URL 自愈恢复);②`handle_immediate_bypass` 调用点不传 damage_assessment(bypass 路径丢定责,尚未触发);③`llm_call_logs` 对网关进程内 run_agent 调用零记录(drain 挂点只覆盖脚本侧,遥测对 E2E 链路不可用)。

**验证**:engine 169(+5)/ gateway 97 / ruff 双干净 / E2E chromium 绿;`test:prompt:compare` 跳过——文本路径 prompt 零改动,基线不可能漂移。
