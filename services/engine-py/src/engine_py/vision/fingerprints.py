"""图证内容指纹账本(2026-10-17 视觉加固 ②①期,vision-evidence-hardening issues/04)。

回答「这张图是否已被别的人拿来索赔过」:triage Step 0.5 评级非空(索赔语境)
时,读本地图算 SHA-256,先查 ``image_fingerprints`` 账本再记账 —— 同
(business_id, sha256) 已有**不同 user** 的先前记录即跨用户复用命中
(字节级相同的图出现在两个账户下,良性解释近零)。

四条纪律(全仓既有裁决同构):
1. **只降级不拒赔**:命中仅 ``suggestedAction→human_review`` + ``fraudFlag``
   增量字段,资金闸仍在金额阈值 + HITL(与 S06 钳制同哲学,叠加不冲突);
2. **失败放行**:DB/读图任何异常 fail-open 不 flag、不炸会话(幽灵单
   ``orderFound`` 异常 fail-open 同裁决)——加固面不可用时不惩罚用户;
3. **租户硬条件**:账本检索 WHERE business_id 等值(多租户不变量 #1);
4. **只存哈希不存图内容**(隐私纪律);同 URL 幂等(多轮重分析不重复记账),
   同用户重传同图只记账不 flag(重试噪声,v2 接订单关联后再收紧)。

v1 边界:仅本地图(``/api/uploads/``,引擎与图同盘可读);公网 http(s) 引用
无法免下载取哈希,跳过不记(v2 随网关侧账本升级)。网关上传侧记账方案
(上传即入账,覆盖未成会话的图)见票 04 的 v2 注记。
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid as _uuid

from sqlalchemy import bindparam, text

from ..db import get_session
from .analyzer import _uploads_dir

_UPLOADS_PREFIX = "/api/uploads/"
_FRAUD_FLAG = "reuse_cross_user"


def _hash_local_image(url: str) -> str | None:
    """本地图引用 → SHA-256 hex;不可读/非本地图返回 None(跳过,不炸)。"""
    if not url.startswith(_UPLOADS_PREFIX):
        return None
    path = _uploads_dir() / url[len(_UPLOADS_PREFIX):]
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def evaluate_reuse(
    rows: list[dict],
    *,
    current_urls: set[str],
    user_id: str | None,
) -> list[dict]:
    """纯函数:账本行 → 跨用户复用命中列表(判定口径单点,测试钉这里)。

    同 URL(多轮重分析)与同用户(重试)与匿名先前记录(user_id 缺失)不 flag。
    """
    hits = []
    for row in rows:
        if row["url"] in current_urls:
            continue
        prior_user = row.get("user_id")
        if not prior_user or not user_id or prior_user == user_id:
            continue
        hits.append({"sha256": row["sha256"], "priorUrl": row["url"], "priorUserId": prior_user})
    return hits


def apply_reuse_flag(damage_assessment: dict, hits: list[dict]) -> dict:
    """命中 → 只降级副本:suggestedAction→human_review + fraudFlag 增量字段。"""
    flagged = dict(damage_assessment)
    if flagged.get("suggestedAction") not in (None, "human_review"):
        flagged["suggestedAction"] = "human_review"
    flagged["fraudFlag"] = _FRAUD_FLAG
    flagged["fraudHits"] = len(hits)
    return flagged


async def _fetch_prior_rows(session, business_id: str, hashes: list[str]) -> list[dict]:
    """账本检索(DB IO 缝,测试 monkeypatch 点);租户硬条件,sha256 批量 IN。"""
    stmt = text("SELECT url, user_id, sha256 FROM image_fingerprints WHERE business_id = :biz AND sha256 IN :hashes").bindparams(
        bindparam("hashes", expanding=True)
    )
    result = await session.execute(stmt, {"biz": business_id, "hashes": hashes})
    return [dict(r._mapping) for r in result.fetchall()]


async def _insert_rows(session, records: list[dict]) -> None:
    """记账(DB IO 缝):同 URL 幂等,多轮重分析不重复入账。"""
    for rec in records:
        await session.execute(
            text(
                "INSERT INTO image_fingerprints (id, business_id, url, sha256, user_id) "
                "VALUES (:id, :biz, :url, :sha256, :uid) ON CONFLICT (url) DO NOTHING"
            ),
            rec,
        )
    await session.commit()


async def audit_image_reuse(
    image_urls: list[str],
    *,
    user_id: str | None,
    business_id: str | None,
) -> dict:
    """反查 + 记账一体入口;任何失败 fail-open(flagged=False),绝不抛。"""
    try:
        local_urls = [u for u in image_urls if isinstance(u, str) and u.startswith(_UPLOADS_PREFIX)]
        if not local_urls or not business_id:
            return {"flagged": False, "hits": [], "checked": 0}
        hashes = await asyncio.gather(*[asyncio.to_thread(_hash_local_image, u) for u in local_urls])
        pairs = [(u, h) for u, h in zip(local_urls, hashes) if h]
        if not pairs:
            return {"flagged": False, "hits": [], "checked": 0}
        async with get_session() as session:
            prior = await _fetch_prior_rows(session, business_id, [h for _, h in pairs])
            hits = evaluate_reuse(prior, current_urls=set(local_urls), user_id=user_id)
            await _insert_rows(
                session,
                [
                    {
                        "id": f"fp_{_uuid.uuid4().hex[:12]}",
                        "biz": business_id,
                        "url": u,
                        "sha256": h,
                        "uid": user_id,
                    }
                    for u, h in pairs
                ],
            )
        return {"flagged": bool(hits), "hits": hits, "checked": len(pairs)}
    except Exception as reuse_err:
        # fail-open:加固面不可用时不惩罚用户,资金闸仍在金额阈值 + HITL
        print(f"[VisionFingerprints] 图证指纹反查失败,放行不 flag: {reuse_err}")
        return {"flagged": False, "hits": [], "degraded": True}
