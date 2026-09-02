"""租户配置注册中心 — 镜像 packages/business-configs/src/tenantRegistryService.ts。

Zero Hardcode:展示名与 SPI/技能配置全部来自 tenants / tenant_configs 物理表,
60 秒进程内缓存。SPI 远程连接器路径未移植(TODO Phase 1b connectors),
无 spiConfig 的租户行为与 TS 一致(local_db 模式直接走本地查询)。
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from sqlalchemy import text

from .db import get_session

_CACHE: dict[str, tuple[dict, float]] = {}
_TTL_SECONDS = 60.0


def invalidate_cache(business_id: str | None = None) -> None:
    if business_id:
        _CACHE.pop(business_id.lower().strip(), None)
    else:
        _CACHE.clear()


async def get_tenant_config(business_id: str = "ecommerce") -> dict:
    clean_id = business_id.lower().strip()
    cached = _CACHE.get(clean_id)
    if cached and time.time() - cached[1] < _TTL_SECONDS:
        return cached[0]

    display_name = f"{clean_id[:1].upper()}{clean_id[1:]} 官方旗舰店"
    system_prompt = (
        f"You are a professional AI Customer Support Agent for {display_name}. "
        "Help customers with order tracking, address modification, refunds, and product inquiries."
    )
    spi_connector: dict = {"mode": "local_db"}
    enabled_skills = ["skill_order_address_modification", "skill_order_refund", "skill_product_inquiry"]
    skills_config: dict = {}

    try:
        async with get_session() as session:
            tenant_row = (
                await session.execute(
                    text("SELECT name, status FROM tenants WHERE LOWER(business_id) = :bid LIMIT 1").bindparams(
                        bid=clean_id
                    )
                )
            ).mappings().first()
            if tenant_row and tenant_row["name"]:
                display_name = tenant_row["name"]

            config_row = (
                await session.execute(
                    text(
                        "SELECT system_prompt, spi_config, enabled_skills, skills_config FROM tenant_configs "
                        "WHERE LOWER(business_id) = :bid ORDER BY version DESC LIMIT 1"
                    ).bindparams(bid=clean_id)
                )
            ).mappings().first()
            if config_row:
                if config_row["system_prompt"]:
                    system_prompt = config_row["system_prompt"]
                if config_row["spi_config"]:
                    spi_connector = (
                        config_row["spi_config"]
                        if isinstance(config_row["spi_config"], dict)
                        else spi_connector
                    )
                if isinstance(config_row["enabled_skills"], list):
                    enabled_skills = config_row["enabled_skills"]
                if isinstance(config_row["skills_config"], dict):
                    skills_config = config_row["skills_config"]
    except Exception as err:  # noqa: BLE001 — 容灾回退默认配置
        print(f"[TenantRegistryService] Failed to load tenant config for {clean_id} from DB: {err}")

    result = {
        "businessId": clean_id,
        "name": display_name,
        "systemPrompt": system_prompt,
        "spiConnector": spi_connector,
        "enabledSkills": enabled_skills,
        "skillsConfig": skills_config,
        "confidenceThresholds": {"high": 0.85, "mid": 0.6},
        "refundAutoApprovalLimit": 50,
    }
    _CACHE[clean_id] = (result, time.time())
    return result


async def update_tenant_skill_config(business_id: str, skill_id: str, skill_config: dict) -> dict:
    """更新或覆盖指定租户的 Skill 配置 — 镜像 TS TenantRegistryService.updateTenantSkillConfig。

    技能级覆写合并进 tenant_configs.skills_config(JSONB)后落盘并失效缓存,
    返回刷新后的完整租户配置(与 get_tenant_config 同构)。
    """
    clean_id = business_id.lower().strip()
    current = await get_tenant_config(clean_id)
    updated_skills_config = {
        **(current.get("skillsConfig") or {}),
        skill_id: {
            "skillId": skill_id,
            "enabled": True if skill_config.get("enabled") is None else skill_config.get("enabled"),
            "approvalThresholdAmount": skill_config.get("approvalThresholdAmount"),
            "customPolicyPrompt": skill_config.get("customPolicyPrompt"),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        },
    }

    try:
        async with get_session() as session:
            existing = (
                await session.execute(
                    text(
                        "SELECT id FROM tenant_configs WHERE LOWER(business_id) = :bid "
                        "ORDER BY version DESC LIMIT 1"
                    ).bindparams(bid=clean_id)
                )
            ).mappings().first()
            if existing:
                await session.execute(
                    # asyncpg 会把 str 参数推断为 VARCHAR,jsonb 列需显式强转
                    text(
                        "UPDATE tenant_configs SET skills_config = CAST(:cfg AS JSONB), updated_at = NOW() "
                        "WHERE id = :id"
                    ).bindparams(cfg=json.dumps(updated_skills_config, ensure_ascii=False), id=existing["id"])
                )
            else:
                await session.execute(
                    text(
                        "INSERT INTO tenant_configs (business_id, system_prompt, spi_config, enabled_skills, "
                        "skills_config, version, status) "
                        "VALUES (:bid, :sp, CAST(:spi AS JSONB), CAST(:es AS JSONB), CAST(:cfg AS JSONB), 1, 'published')"
                    ).bindparams(
                        bid=clean_id,
                        sp=current.get("systemPrompt") or "",
                        spi=json.dumps(current.get("spiConnector") or {"mode": "local_db"}),
                        es=json.dumps(current.get("enabledSkills") or []),
                        cfg=json.dumps(updated_skills_config, ensure_ascii=False),
                    )
                )
            await session.commit()
    except Exception as err:  # noqa: BLE001 — 与 TS 基线一致,落盘失败仅告警不阻断
        print(f"[TenantRegistryService] Failed to persist tenant skill config for {clean_id}: {err}")

    invalidate_cache(clean_id)
    return await get_tenant_config(clean_id)
