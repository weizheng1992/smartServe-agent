# 02 — 双层画像隔离拓扑与防投毒装配 (Dual-Tier Scoped Persona & Context Isolation)

**What to build:** 建立多租户安全上下文防投毒隔离拓扑。在数据库与长期记忆引擎中引入 `global`（全局客观生理/身体事实，如脚长 270mm、布料过敏）与 `tenant`（特定商户私域偏好与优惠）双层画像作用域。专职画像分析 Agent（Profiler Agent）在提取偏好时自动判别作用域；`ContextAssemblyPipeline` 与 `LongMemory` 召回时严格限定为 `(scope = 'global' OR business_id = currentTenant)`，彻底绝杜竞品品牌信息泄露与跨租户越权（IDOR）。

**Blocked by:** None — can start immediately.

**Status:** closed

- [x] 演进 `long_memory_facts` 和 `episodic_events` 数据库表结构，新增 `business_id` 与 `scope`（`'global'` | `'tenant'`）字段及索引
- [x] 升级 Profiler Agent 提示词与提取解析器，将生理尺寸/过敏原自动归类为 `global`，将品牌鞋款/优惠互动归类为 `tenant`
- [x] 优化 `LongMemory.searchRelevantFacts` 与 `ContextAssemblyPipeline.assemble`，仅检索并装配与当前会话租户匹配的画像切片
- [x] 编写跨商户上下文隔离测试：模拟同一用户在 Nike 与 Adidas 店铺分别沉淀事实，验证在 Adidas 店铺中能召回身体全局事实，但 Nike 专属偏好被 100% 物理阻断
