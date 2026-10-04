"""租户管理域(架构审查 #6 下沉,2026-10-04):admin.py 租户 CRUD 的 SQL 与
合并覆写语义的唯一归属。此前 create/update 两个 ~145 行处理器各自内嵌
tenants / tenant_configs 裸 SQL(tenant_configs 新行 INSERT 逐字两份、合并
覆写语义双份维护),删除测试不通过 —— 删掉路由,290 行 SQL 原样重现于任何
替代者体内。本 module 收拢后路由退回 HTTP 适配(DTO 校验 + 异常翻译)。

Interface(调用方须知的一切):

- ``list_tenant_summaries() -> list[dict]``:租户列表行(TENANTS ⨝ tenant_configs,
  编辑面回读 onboardingConfig,无配置回 None 不伪造默认值)。DB 故障由调用方
  决定降级呈现(路由保留「success True + 空表 + message」的历史形状)。
- ``upsert_tenant(...)``:创建流(ON CONFLICT 覆写 tenants 主行;tenant_configs
  既有行合并式仅携带 onboardingConfig 时写,新行走 INSERT)。
- ``update_tenant(...)``:编辑流。查无 → ``LookupError``;内置业务域(builtin)
  停用 → ``PermissionError``;合并式覆写:仅请求显式携带的字段落写。
- ``delete_tenant(...)``:删除流。builtin → ``PermissionError``。

写后统一 ``invalidate_cache``(缓存失效随写走,调用方免记)。HTTP 状态翻译
(LookupError→404 / PermissionError→403)留在路由 —— 呈现按面适配。
"""

from __future__ import annotations

import json

from engine_py.db import get_session
from engine_py.tenant_config import invalidate_cache
from sqlalchemy import text

_DEFAULT_SKILLS_ARR = ["skill_order_address_modification", "skill_order_refund", "skill_product_inquiry"]


async def _insert_tenant_configs(
    session,
    *,
    business_id: str,
    name: str,
    spi_config: dict,
    skills_config: dict,
    onboarding: dict | None,
) -> None:
    """tenant_configs 新行 INSERT 单点:create 与 update-缺行两分支此前逐字
    各抄 18 行,列清单漂移风险收拢于此。"""
    await session.execute(
        text(
            "INSERT INTO tenant_configs (business_id, system_prompt, welcome_message, status, version, "
            "spi_config, enabled_skills, skills_config, onboarding_config) "
            "VALUES (:bid, :prompt, :welcome, 'published', 1, CAST(:spi AS jsonb), CAST(:skills_arr AS jsonb), "
            "CAST(:skills AS jsonb), CAST(:onboarding AS jsonb))"
        ).bindparams(
            bid=business_id,
            prompt=f"You are the official AI Customer Support Agent for {name}.",
            welcome=f"您好！欢迎来到 {name}，请问有什么可以帮您？",
            spi=json.dumps(spi_config),
            skills_arr=json.dumps(_DEFAULT_SKILLS_ARR),
            skills=json.dumps(skills_config),
            onboarding=json.dumps(onboarding) if onboarding is not None else None,
        )
    )


async def list_tenant_summaries() -> list[dict]:
    """租户列表行(admin 租户页 DTO:密钥/阈值/回调/引导配置回读)。"""
    async with get_session() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT t.business_id, t.name, t.status, t.industry, t.created_at, t.plan_tier, "
                        "tc.spi_config, tc.skills_config, tc.onboarding_config "
                        "FROM tenants t LEFT JOIN tenant_configs tc ON LOWER(t.business_id) = LOWER(tc.business_id) "
                        "ORDER BY t.created_at DESC"
                    )
                )
            )
            .mappings()
            .all()
        )
    tenants = []
    for row in rows:
        spi = row["spi_config"] if isinstance(row["spi_config"], dict) else {}
        skills_cfg = row["skills_config"] if isinstance(row["skills_config"], dict) else {}
        refund_cfg = skills_cfg.get("skill_order_refund")
        refund_limit = (
            refund_cfg.get("approvalThresholdAmount")
            if isinstance(refund_cfg, dict) and refund_cfg.get("approvalThresholdAmount") is not None
            else None
        )
        tenants.append(
            {
                "id": row["business_id"],
                "name": row["name"],
                "industry": row["industry"] or "综合零售",
                "channel": "Web + Mobile + SPI",
                # 未配置即回 null,前端「未配置」态呈现(数据真实性约定:严禁编造
                # 密钥/风控阈值/Webhook 地址——update 路由对 falsy 值不覆写,回传安全)
                "apiKey": spi.get("apiSecret"),
                "refundLimit": refund_limit,
                "autoEscalation": True,
                "webhookUrl": spi.get("spiBaseUrl"),
                "status": row["status"] or "active",
                "planTier": row["plan_tier"] or "free",
                "createdAt": row["created_at"].isoformat().split("T")[0] if row["created_at"] else None,
                # 编辑面回读(new-user-onboarding E):无配置租户回 None,
                # 前端 JSON 文本域以「未配置」态呈现而非伪造默认值
                "onboardingConfig": (
                    row["onboarding_config"] if isinstance(row["onboarding_config"], dict) else None
                ),
            }
        )
    return tenants


async def upsert_tenant(
    *,
    business_id: str,
    name: str,
    status: str | None,
    industry: str | None,
    webhook_url: str | None,
    api_key: str | None,
    refund_limit: int | None,
    onboarding_config: dict | None,
) -> None:
    """创建流:tenants 主行 ON CONFLICT 覆写;spi/skills 配置按「未配置即不落库」
    组装(数据真实性约定);tenant_configs 既有行合并式仅携带 onboardingConfig
    时写,新行走 INSERT。"""
    spi_config = {"mode": "remote_spi", "timeoutMs": 5000}
    if webhook_url:
        spi_config["spiBaseUrl"] = webhook_url
    if api_key:
        spi_config["apiSecret"] = api_key
    skills_config = {"skill_order_refund": {"enabled": True}}
    if refund_limit is not None:
        skills_config["skill_order_refund"]["approvalThresholdAmount"] = refund_limit

    async with get_session() as session:
        await session.execute(
            text(
                "INSERT INTO tenants (business_id, name, plan_tier, status, industry) "
                "VALUES (:bid, :name, 'enterprise', :status, :industry) "
                "ON CONFLICT (business_id) DO UPDATE SET name = EXCLUDED.name, status = EXCLUDED.status, "
                "industry = COALESCE(EXCLUDED.industry, tenants.industry)"
            ).bindparams(bid=business_id, name=name, status=status or "active", industry=industry)
        )
        existing = (
            await session.execute(
                text("SELECT id FROM tenant_configs WHERE LOWER(business_id) = :bid LIMIT 1").bindparams(bid=business_id)
            )
        ).scalar_one_or_none()
        if existing:
            # 合并式:仅当请求携带 onboardingConfig 时写入(重建既有租户未携带 → 不动既有引导配置)
            if onboarding_config is not None:
                await session.execute(
                    text(
                        "UPDATE tenant_configs SET spi_config = :spi, skills_config = :skills, "
                        "onboarding_config = CAST(:onboarding AS jsonb), updated_at = NOW() WHERE id = :cid"
                    ).bindparams(
                        spi=json.dumps(spi_config),
                        skills=json.dumps(skills_config),
                        onboarding=json.dumps(onboarding_config),
                        cid=existing,
                    )
                )
            else:
                await session.execute(
                    text("UPDATE tenant_configs SET spi_config = :spi, skills_config = :skills, updated_at = NOW() WHERE id = :cid").bindparams(
                        spi=json.dumps(spi_config), skills=json.dumps(skills_config), cid=existing
                    )
                )
        else:
            await _insert_tenant_configs(
                session,
                business_id=business_id,
                name=name,
                spi_config=spi_config,
                skills_config=skills_config,
                onboarding=onboarding_config,
            )
        await session.commit()
    invalidate_cache(business_id)


async def update_tenant(
    *,
    business_id: str,
    name: str,
    status: str | None,
    industry: str | None,
    webhook_url: str | None,
    api_key: str | None,
    refund_limit: int | None,
    onboarding_config: dict | None,
) -> None:
    """编辑流:查无 LookupError;builtin 停用 PermissionError(admin-readiness 02);
    tenant_configs 合并式覆写 —— 仅请求显式携带的字段落写,避免整份覆写丢失既有配置。"""
    async with get_session() as session:
        existing = (
            await session.execute(
                text("SELECT id, plan_tier FROM tenants WHERE LOWER(business_id) = :bid LIMIT 1").bindparams(bid=business_id)
            )
        ).mappings().first()
        if not existing:
            raise LookupError(f"Tenant '{business_id}' not found")
        # 内置业务域保护(admin-readiness 02):builtin 是 nightly 评测/密封契约的
        # 依赖基线,禁停用(名称/行业仍可改);一行误删全线爆炸
        if existing["plan_tier"] == "builtin" and (status or "active") != "active":
            raise PermissionError(f"内置业务域 '{business_id}' 不可停用")

        await session.execute(
            text(
                "UPDATE tenants SET name = :name, status = :status, industry = COALESCE(:industry, industry) "
                "WHERE LOWER(business_id) = :bid"
            ).bindparams(name=name, status=status or "active", industry=industry, bid=business_id)
        )

        cfg_row = (
            await session.execute(
                text(
                    "SELECT id, spi_config, skills_config, onboarding_config FROM tenant_configs "
                    "WHERE LOWER(business_id) = :bid LIMIT 1"
                ).bindparams(bid=business_id)
            )
        ).mappings().first()
        spi = dict(cfg_row["spi_config"]) if isinstance(cfg_row and cfg_row["spi_config"], dict) else {}
        skills = dict(cfg_row["skills_config"]) if isinstance(cfg_row and cfg_row["skills_config"], dict) else {}
        if webhook_url:
            spi["spiBaseUrl"] = webhook_url
        if api_key:
            spi["apiSecret"] = api_key
        spi.setdefault("mode", "remote_spi")
        spi.setdefault("timeoutMs", 5000)
        if refund_limit is not None:
            refund_cfg = skills.get("skill_order_refund")
            refund_cfg = dict(refund_cfg) if isinstance(refund_cfg, dict) else {}
            refund_cfg["enabled"] = refund_cfg.get("enabled", True)
            refund_cfg["approvalThresholdAmount"] = refund_limit
            skills["skill_order_refund"] = refund_cfg
        # onboarding_config:请求携带即整体覆写(完整 schema 文档),未携带保留既有
        onboarding = (
            dict(onboarding_config)
            if onboarding_config is not None
            else (dict(cfg_row["onboarding_config"]) if isinstance(cfg_row and cfg_row["onboarding_config"], dict) else None)
        )

        if cfg_row:
            await session.execute(
                text(
                    "UPDATE tenant_configs SET spi_config = CAST(:spi AS jsonb), skills_config = CAST(:skills AS jsonb), "
                    "onboarding_config = CAST(:onboarding AS jsonb), updated_at = NOW() WHERE id = :cid"
                ).bindparams(
                    spi=json.dumps(spi),
                    skills=json.dumps(skills),
                    onboarding=json.dumps(onboarding) if onboarding is not None else None,
                    cid=cfg_row["id"],
                )
            )
        else:
            await _insert_tenant_configs(
                session,
                business_id=business_id,
                name=name,
                spi_config=spi,
                skills_config=skills,
                onboarding=onboarding,
            )
        await session.commit()
    invalidate_cache(business_id)


async def delete_tenant(*, business_id: str) -> None:
    """删除流:builtin PermissionError(admin-readiness 02,评测/契约依赖基线禁删)。"""
    async with get_session() as session:
        plan_tier = (
            await session.execute(
                text("SELECT plan_tier FROM tenants WHERE LOWER(business_id) = :bid LIMIT 1").bindparams(bid=business_id)
            )
        ).scalar_one_or_none()
        if plan_tier == "builtin":
            raise PermissionError(f"内置业务域 '{business_id}' 不可删除(生产可用 SEED_BUILTIN_TENANTS 控制播种)")
        await session.execute(
            text("DELETE FROM tenant_configs WHERE LOWER(business_id) = :bid").bindparams(bid=business_id)
        )
        await session.execute(text("DELETE FROM tenants WHERE LOWER(business_id) = :bid").bindparams(bid=business_id))
        await session.commit()
    invalidate_cache(business_id)
