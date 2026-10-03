"""意图数据飞轮(ADR-0005)的包内 CLI 群 —— 标注/评测/标定/回捞七件套。

唯一入口 ``python -m engine_py.intent_flywheel.<cli>``:

- backhaul_unanswered       未命中问句回捞(增长飞轮闭环)
- export_intent_data        数据水龙头(三张积累表 → JSONL)
- review_badcase            坏例人审定性(通道②)
- backfill_outcome_from_rules  历史问句规则复判(通道③)
- gen_intent_cases          生成意图评测集
- run_intent_eval           确定性层跑分(闸门 95%)
- calibrate_semantic_routes 语义路由阈值标定

共享 toolkit(JSONL 读写、CLI .env 装载)在 ``common.py``;包内 module
零路径 hack、常规 import 即可用(由 tests/test_flywheel_importable.py
钉死)。训练轨(``scripts/training/``)为二步收编,暂留原位。
"""
