"""codegen 漂移门(ADR-0015 批一/批二)。

① Python/TS/docs 三类生成物文件内容必须与 emitter 全文相等(声明改了没再生成 → 红);
② 生成物 import 后的常量与 registry 派生值相等(生成器语义漂移 → 红);
③ schema 卡投影(批二)与声明层一致,列裁剪生效。

engine/gateway 运行时只 import 生成物(engine_py.ontology_generated,自包含
零依赖);声明层 → 生成物 的唯一再生成入口:
`services/.venv/bin/python ontology/registry.py --write-all`
"""

from __future__ import annotations

from ontology import (
    CARD_MAIN_ORDER,
    CARD_SPECIAL_ORDER,
    CUSTOMER_ACTIONS,
    DEFAULT_REFUND_AUTO_APPROVAL_LIMIT,
    ENGINE_HANDLED_ACTIONS,
    GENERATED_DOCS_PATH,
    GENERATED_PY_PATH,
    GENERATED_TS_PATH,
    OPERATOR_ACTIONS,
    SPI_ACTIONS,
    STAFF_REVIEW_ACTIONS,
    TS_GHOST_ACTIONS,
    card_projection,
    emit_docs,
    emit_python,
    emit_typescript,
)

_REGEN_HINT = "改了 ontology/*.yaml 须执行 `services/.venv/bin/python ontology/registry.py --write-all` 再提交"


def test_generated_file_in_sync() -> None:
    assert GENERATED_PY_PATH.exists(), f"生成物缺失:{GENERATED_PY_PATH}"
    assert GENERATED_PY_PATH.read_text(encoding="utf-8") == emit_python(), (
        "ontology_generated.py 与声明层漂移 —— " + _REGEN_HINT
    )


def test_generated_ts_in_sync() -> None:
    assert GENERATED_TS_PATH.exists(), f"生成物缺失:{GENERATED_TS_PATH}"
    assert GENERATED_TS_PATH.read_text(encoding="utf-8") == emit_typescript(), (
        "ontology-actions.ts 与声明层漂移 —— " + _REGEN_HINT
    )


def test_generated_docs_in_sync() -> None:
    assert GENERATED_DOCS_PATH.exists(), f"生成物缺失:{GENERATED_DOCS_PATH}"
    assert GENERATED_DOCS_PATH.read_text(encoding="utf-8") == emit_docs(), (
        "ontology.md 知识地图与声明层漂移 —— " + _REGEN_HINT
    )


def test_generated_module_constants_match_registry() -> None:
    from engine_py import ontology_generated as gen

    assert gen.CUSTOMER_ACTIONS == CUSTOMER_ACTIONS
    assert gen.OPERATOR_ACTIONS == OPERATOR_ACTIONS
    assert gen.STAFF_REVIEW_ACTIONS == STAFF_REVIEW_ACTIONS
    assert gen.SPI_ACTIONS == SPI_ACTIONS
    assert gen.ENGINE_HANDLED_ACTIONS == ENGINE_HANDLED_ACTIONS
    assert gen.TS_GHOST_ACTIONS == TS_GHOST_ACTIONS
    assert gen.DEFAULT_REFUND_AUTO_APPROVAL_LIMIT == DEFAULT_REFUND_AUTO_APPROVAL_LIMIT
    assert set(gen.APPROVAL_ACTIONS) == set(ENGINE_HANDLED_ACTIONS)


def test_generated_cards_match_projection() -> None:
    from engine_py import ontology_generated as gen

    cards = card_projection()
    assert tuple(gen.MAIN_CARD_TABLES) == CARD_MAIN_ORDER
    assert tuple(gen.SPECIAL_FAMILY_TABLES) == CARD_SPECIAL_ORDER
    assert gen.MAIN_CARD_TABLES == cards["main"]
    assert gen.SPECIAL_FAMILY_TABLES == cards["special"]
    # 列裁剪生效:客户表分析卡只含 3 列(PII 列 name/phone 不进 T2 prompt)
    assert set(gen.MAIN_CARD_TABLES["merchant_customers"]["columns"]) == {
        "id", "customer_id", "member_level",
    }
    # 卡列 ⊆ 实体全列(声明层闭包;发明列在 registry 校验即红)
    for group in cards.values():
        for table, entry in group.items():
            entity_cols = set(gen.ONTOLOGY_ENTITIES[table]["columns"])
            assert set(entry["columns"]) <= entity_cols, table
