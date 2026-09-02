"""租户配置注册中心 — 镜像 packages/business-configs/src/tenantRegistryService.ts。

Zero Hardcode:展示名与 SPI/技能配置全部来自 tenants / tenant_configs 物理表,
60 秒进程内缓存。SPI 远程连接器路径未移植(TODO Phase 1b connectors),
无 spiConfig 的租户行为与 TS 一致(local_db 模式直接走本地查询)。
"""

from __future__ import annotations

import time

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
