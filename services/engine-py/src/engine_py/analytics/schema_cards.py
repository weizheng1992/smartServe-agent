"""schema 卡片(08-D2:编译期生成,确定性进解析上下文)。

批二(ADR-0015)起事实源 = ontology/domain/*.yaml —— 经
``engine_py.ontology_generated`` 编译分发,由 registry.card_projection 派生
(列裁剪 analysis_columns ⊆ columns 在声明层闭包校验)。本模块只保留分组
语义与文本渲染,**手抄列卡形态退役**:列漂移(membership≠member_level 类)
由声明层校验 + semantic_compiler._assert_model_matches_card 列级断言双闸杜绝。
"""

from __future__ import annotations

from typing import Any

from ..ontology_generated import (
    CARD_MAIN_ORDER,
    MAIN_CARD_TABLES,
    SPECIAL_FAMILY_TABLES,
)

# 主卡 = merchant_db ∧ 非营销域(进 L3 上下文 prompt,token 成本 08-D2 冻结);
# special 族 = 营销域 merchant 实体 + engine_db 实体(仅编译期 AST 表白名单,
# 不进 prompt)。分组规则与表序由 ontology registry 校验(_validate_card_grouping
# + CARD_*_ORDER 冻结序),此处不再持有任何列卡事实。


def merchant_schema_card() -> dict[str, Any]:
    """商户库 schema 卡片(主卡 7 表;冻结结构供 AST 校验与 L3 上下文)。"""
    return {"database": "agent_merchant", "tables": dict(MAIN_CARD_TABLES)}


def compile_safe_schema_card() -> dict[str, Any]:
    """编译期安全闸联合卡(主卡 7 表 + special-family 表)。

    两条编译路径(销售族/特殊族)统一喂这一张表,保证模板新增表必须先在
    本体 domain 声明并重新生成,否则安全闸响亮拒绝 —— 表白名单单点收口。
    """
    return {"database": "agent_merchant", "tables": {**MAIN_CARD_TABLES, **SPECIAL_FAMILY_TABLES}}


def schema_card_text() -> str:
    """紧凑文本形态(喂 L3 兜底层用;每表一行,列名拼接;行序 = CARD_MAIN_ORDER 冻结序)。"""
    lines = []
    for table in CARD_MAIN_ORDER:
        spec = MAIN_CARD_TABLES[table]
        cols = ", ".join(spec["columns"].keys())
        note = f" — {spec['notes']}" if spec["notes"] else ""
        lines.append(f"{table}({cols}){note}")
    return "\n".join(lines)
