"""「该找谁」责任人路由解析器(spec .scratch/owner-routing §2-§3)。

确定性、零 LLM:问句词面 → 闭集目标(品类/商品/指标)→ owner_mappings →
staff_members。商户库走只读 reader 实时读(不缓存 —— owner 陈旧比慢更糟);
映射存在但员工查无/停用与未登记同归 None(呈现层统一诚实降级,不区分暴露)。

安全边界(Q13 硬性):本模块是责任人数据的唯一读取口 —— owner_mappings 不进
T2 schema 白名单、不进任何 LLM 上下文;LLM 永远摸不到通讯录,自由 SQL 无绕闸面。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select, text

from ..db import get_session
from ..db.merchant_access import reader_engine, writer_engine
from ..db.models import StaffMember
from .tools_registry_bridge import metric_semantic_registry, semantic_model

MAP_CATEGORY = "category"
MAP_METRIC = "metric"
MAP_SPU = "spu"
MAP_PROMOTION = "promotion"

# 「找谁」问句词面(Q9):命中才进入快轨,其余问句零感知。
_OWNER_ASK_RE = re.compile(r"找谁|谁负责|负责人|谁管|找哪位|该找谁")
_SPU_CODE_RE = re.compile(r"SPU-[A-Za-z0-9-]+")


def has_reason_intent(question: str) -> bool:
    """原因语感(单源在 composition.REASON_RE;找谁 × 指标 × 原因 = 复合问升格)。"""
    from .composition import REASON_RE

    return bool(REASON_RE.search(question or ""))


@dataclass(frozen=True)
class OwnerTarget:
    """快轨识别出的问句目标(闭集之一)。"""

    map_type: str  # category | metric | spu
    map_value: str  # 品类词 / 指标 key / SPU 编码
    label: str  # 展示名(品类词 / 指标 label / 商品标题)


@dataclass(frozen=True)
class OwnerInfo:
    staff_id: str
    display: str
    dept: str | None
    level: str | None
    email: str
    role: str


def format_name(info: OwnerInfo) -> str:
    """「张三(销售部·主管)」—— 缺段省略(Q10 归因卡列点名形)。"""
    suffix = "·".join(p for p in (info.dept, info.level) if p)
    return f"{info.display}({suffix})" if suffix else info.display


def looks_like_owner_ask(question: str) -> bool:
    return bool(_OWNER_ASK_RE.search(question))


def _metric_wordfaces() -> list[tuple[str, str]]:
    """(词面, 指标 key),长词面优先 —— 「总销售额」必须压过同义词「销售额」;
    label/去括号/synonyms 三源常同文,去重免重复扫描。"""
    faces: list[tuple[str, str]] = []
    for key, meta in metric_semantic_registry().items():
        label = str(meta.get("label") or "")
        base = label.split("(")[0].split("（")[0].strip()
        candidates = (label, base, *(str(s).strip() for s in (meta.get("synonyms") or [])))
        for face in dict.fromkeys(candidates):
            if len(face) >= 2:
                faces.append((face, key))
    faces.sort(key=lambda pair: len(pair[0]), reverse=True)
    return faces


async def find_owner_target(question: str) -> OwnerTarget | None:
    """闭集词面定位目标,**具体专名优先于泛类词**:商品编码精确 → 活动名/前段
    → 商品标题包含(唯一)→ 品类枚举包含 → 指标词面。活动名常内嵌品类词
    (「国庆户外机能节」⊃「户外机能」),泛类先命中会把「活动谁搞的」错答成
    品类负责人 —— 顺序即语义。单目标,首个命中即返回;全不中返回 None。"""
    async with reader_engine().connect() as conn:
        spus = (await conn.execute(text("SELECT spu_code, title FROM merchant_spus"))).all()
        promos = (await conn.execute(text("SELECT name FROM promotions"))).all()

    code_match = _SPU_CODE_RE.search(question)
    if code_match:
        code = code_match.group(0)
        for spu_code, title in spus:
            if spu_code == code:
                return OwnerTarget(MAP_SPU, spu_code, title)
    for (promo_name,) in promos:
        base = promo_name.split("·")[0].strip()
        if promo_name in question or (len(base) >= 4 and base in question):
            return OwnerTarget(MAP_PROMOTION, promo_name, promo_name)
    title_hits = []
    for code, title in spus:
        if not title:
            continue
        base = title.split(" (")[0].split("（")[0].strip()
        if title in question or (len(base) >= 6 and base in question):
            title_hits.append((code, title))
    if len(title_hits) == 1:
        return OwnerTarget(MAP_SPU, title_hits[0][0], title_hits[0][1])

    for value in sorted(semantic_model()["dimensions"]["category"]["values"], key=len, reverse=True):
        if value in question:
            return OwnerTarget(MAP_CATEGORY, value, value)

    for face, key in _metric_wordfaces():
        if face in question:
            return OwnerTarget(MAP_METRIC, key, str(metric_semantic_registry()[key].get("label") or key))
    return None


async def _mapped_staff_ids(map_type: str, values: list[str]) -> dict[str, str | None]:
    """键类型 → staff_id 来源路由:品类/指标走注册表;商品/活动走实体列
    (Q14/Q15 数据原生 —— 实体的所有权长在实体行上,不进注册表)。"""
    async with reader_engine().connect() as conn:
        if map_type == MAP_SPU:
            rows = (
                await conn.execute(
                    text("SELECT spu_code, owner_id FROM merchant_spus WHERE spu_code = ANY(:vs)"),
                    {"vs": values},
                )
            ).all()
        elif map_type == MAP_PROMOTION:
            rows = (
                await conn.execute(
                    text("SELECT name, created_by FROM promotions WHERE name = ANY(:vs)"),
                    {"vs": values},
                )
            ).all()
        else:
            rows = (
                await conn.execute(
                    text(
                        "SELECT map_value, staff_id FROM owner_mappings "
                        "WHERE map_type = :t AND map_value = ANY(:vs)"
                    ),
                    {"t": map_type, "vs": values},
                )
            ).all()
    return {value: staff_id for value, staff_id in rows}


async def resolve_owners(
    business_id: str, map_type: str, values: list[str]
) -> dict[str, OwnerInfo | None]:
    """批量解析:商户库所有权威源(实时)→ engine 员工(在职闸)。任一环缺失 → None。"""
    unique = [v for v in dict.fromkeys(values) if v]
    if not unique:
        return {}
    mapped = await _mapped_staff_ids(map_type, unique)
    staff_by_id: dict[str, StaffMember] = {}
    staff_ids = sorted({sid for sid in mapped.values() if sid})
    if staff_ids:
        async with get_session() as session:
            staff_rows = (
                await session.execute(
                    select(StaffMember).where(
                        StaffMember.business_id == business_id,
                        StaffMember.id.in_(staff_ids),
                        StaffMember.status == "enabled",
                    )
                )
            ).scalars().all()
        staff_by_id = {s.id: s for s in staff_rows}
    result: dict[str, OwnerInfo | None] = {}
    for value in unique:
        staff = staff_by_id.get(mapped.get(value, ""))
        result[value] = (
            OwnerInfo(
                staff_id=staff.id,
                display=staff.display_name,
                dept=staff.dept,
                level=staff.level,
                email=staff.email,
                role=staff.role,
            )
            if staff
            else None
        )
    return result


async def resolve_owner(business_id: str, target: OwnerTarget) -> OwnerInfo | None:
    return (await resolve_owners(business_id, target.map_type, [target.map_value])).get(target.map_value)


# ---------------- 维护面(spec §5):注册表读写的单一实现 ----------------
# spu/promotion 是数据原生列(Q14/Q15),不归注册表管辖 —— CRUD 只管
# category/metric 两种键;map_value 闭集校验取语义注册表,防脏键入库。


async def upsert_mapping(business_id: str, map_type: str, map_value: str, staff_id: str) -> dict:
    """登记/改派责任人。闭集校验(键型/维度值/员工在职)任一不过 → {"error": ...}。"""
    map_type = (map_type or "").strip()
    map_value = (map_value or "").strip()
    staff_id = (staff_id or "").strip()
    if map_type not in (MAP_CATEGORY, MAP_METRIC):
        return {"error": "mapType ∈ category|metric(商品/活动所有权随实体行,不在此登记)"}
    if not map_value or not staff_id:
        return {"error": "mapValue/staffId 必传"}
    if map_type == MAP_CATEGORY:
        if map_value not in semantic_model()["dimensions"]["category"]["values"]:
            return {"error": f"mapValue 不是注册品类:{map_value}"}
    else:
        if map_value not in metric_semantic_registry():
            return {"error": f"mapValue 不是注册指标:{map_value}"}
    async with get_session() as session:
        staff = (
            await session.execute(
                select(StaffMember).where(
                    StaffMember.business_id == business_id,
                    StaffMember.id == staff_id,
                    StaffMember.status == "enabled",
                )
            )
        ).scalars().first()
        if staff is None:
            return {"error": "staffId 不是本店在职员工"}
    async with writer_engine().begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO owner_mappings (map_type, map_value, staff_id) VALUES (:t, :v, :s) "
                "ON CONFLICT (map_type, map_value) DO UPDATE SET staff_id = EXCLUDED.staff_id, "
                "updated_at = NOW()"
            ),
            {"t": map_type, "v": map_value, "s": staff_id},
        )
    return {"mapType": map_type, "mapValue": map_value, "staffId": staff_id}


async def delete_mapping(map_type: str, map_value: str) -> dict:
    """撤销登记(下轮解析即「未登记」,诚实降级)。"""
    map_type = (map_type or "").strip()
    map_value = (map_value or "").strip()
    if map_type not in (MAP_CATEGORY, MAP_METRIC):
        return {"error": "mapType ∈ category|metric"}
    if not map_value:
        return {"error": "mapValue 必传"}
    async with writer_engine().begin() as conn:
        await conn.execute(
            text("DELETE FROM owner_mappings WHERE map_type = :t AND map_value = :v"),
            {"t": map_type, "v": map_value},
        )
    return {"deleted": True}


async def list_mappings() -> list[dict]:
    """全量映射(维护页列表用;含员工展示字段,停用员工照列 —— 呈现层标停用)。"""
    async with reader_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(
                    'SELECT map_type AS "mapType", map_value AS "mapValue", staff_id AS "staffId", '
                    'owner_type AS "ownerType", updated_at AS "updatedAt" FROM owner_mappings '
                    "ORDER BY map_type, map_value"
                )
            )
        ).mappings().all()
    mappings = [dict(r) for r in rows]
    staff_ids = sorted({m["staffId"] for m in mappings})
    staff_by_id: dict[str, StaffMember] = {}
    if staff_ids:
        async with get_session() as session:
            staff_rows = (
                await session.execute(select(StaffMember).where(StaffMember.id.in_(staff_ids)))
            ).scalars().all()
            staff_by_id = {s.id: s for s in staff_rows}
    for m in mappings:
        staff = staff_by_id.get(m["staffId"])
        m["displayName"] = staff.display_name if staff else None
        m["dept"] = staff.dept if staff else None
        m["level"] = staff.level if staff else None
        m["enabled"] = bool(staff and staff.status == "enabled")
    return mappings
