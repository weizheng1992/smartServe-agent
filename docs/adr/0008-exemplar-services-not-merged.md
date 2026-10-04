# ADR-0008: 意图示例与查询示例两服务不合并(triage/exemplar_service ≠ analytics/exemplar_service)

- 日期: 2026-10-03
- 状态: 已决议(2026-10-02 夜审 A9「exemplar_service 两份骨架」候选的终局裁决;同日 analytics 架构深化 C1-C6 落地时复核)
- 关联: ADR-0004/0005(L2 范例回放)、`engine_py/vectors.py`(余弦/embedding 解析单一实现)

## 背景

仓库存在两个同名 `exemplar_service`,夜审列为重复实现候选:

| | `triage/exemplar_service.py`(143L) | `analytics/exemplar_service.py`(92L) |
|---|---|---|
| 表 | `IntentExemplar`(intent_name + example_text) | `QueryExemplar`(intent_json 结构化意图) |
| 消费方 | structured_classifier / intent_triage_engine / llm_refine(客服意图 few-shot) | graph._fallback_intent(数据问句 L2 范例回放) |
| 检索语义 | **喂 prompt 的上下文**:top-N 列表,阈值地板 0.05,n-gram 文本重叠与余弦取 max,0.2s 超时降级空列表(工单05) | **单裁决**:最高分 ≥0.90 严格阈值才回放结构化意图,低分不兜底(08-P1 响亮失败) |
| 池 | 租户单池 | 双池(`__global__` + 租户) |
| 生命周期 | 无停用(样本随种子管理) | deactivate(实体删除后防持续劫持,ADR-0005 后续①) |

## 决策

**不合并。** 两者的 interface 在六个轴上互斥(返回形状/阈值语义/评分混合/池scope/生命周期/超时策略),任何通用化都需要六参数适配——「deletion test」不通过:删掉任何一个服务,其域内复杂度都会原样重新出现,两者都不是 pass-through。它们只是共享了 ~15 行「embed 文本 → 落行」的骨架,而这层骨架的真底座(`vectors.py` 的余弦与 embedding 解析)已于 2026-10-02 收敛单一实现。

**同批落地**:analytics/exemplar_service 对 `cosine_similarity` 的引用改从 `..vectors` 直取(此前经 `triage/semantic_cache` 转发名跨域 import——analytics→triage 的域边只为一个转发名存在);`semantic_cache` 的转发名保留,服务 triage 域内消费方(semantic_routes / intent_classifier / triage.__init__)。

## 否决项

- 抽取通用 `ExemplarPool` 基类/泛型池(六参数参数汤,比两份可读的领域模块更难懂)。
- 让 analytics 复用 triage 的 n-gram 重叠混合(分析问句错配代价高,0.90 纯余弦是刻意收紧,ADR-0005 载明)。
- 让 triage 套用 0.90 严格阈值(few-shot 喂给需要宽召回地板,0.05 是刻意的)。

## 后果

- 未来复审(夜审/架构巡检)对本重复不再立案;本 ADR 即裁决记录。
- 若某日两域检索语义真趋同(例如意图层也走闭集裁决),须先推翻本 ADR 的「检索语义互斥」前提,再议合并。
