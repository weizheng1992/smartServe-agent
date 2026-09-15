"""技能基类 — 租户配置覆盖 + 风控阈值 + SPI 客户端;进出为类型化契约。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..tenant_config import get_tenant_config
from .contract import SkillContext, SkillResult
from .spi_client import LocalDbSpiAdapter


class BaseSkill(ABC):
    metadata: dict

    def can_handle(self, context: SkillContext) -> bool:
        active_intent = context.slots.get("activeIntent") or context.extra.get("intent") or ""
        return active_intent in self.metadata.get("triggerIntents", [])

    async def get_effective_config(self, tenant_id: str) -> dict | None:
        tenant_config = await get_tenant_config(tenant_id)
        skills_config = tenant_config.get("skillsConfig") or {}
        if self.metadata["id"] in skills_config:
            return skills_config[self.metadata["id"]]
        enabled_skills = tenant_config.get("enabledSkills")
        is_enabled = not enabled_skills or self.metadata["id"] in enabled_skills
        return {
            "skillId": self.metadata["id"],
            "enabled": is_enabled,
            "approvalThresholdAmount": self.metadata.get("approvalThresholdAmount"),
        }

    async def get_effective_approval_threshold(self, tenant_id: str) -> float:
        config = await self.get_effective_config(tenant_id)
        if config and config.get("approvalThresholdAmount") is not None:
            return float(config["approvalThresholdAmount"])
        return float(self.metadata.get("approvalThresholdAmount") or 50)

    @abstractmethod
    async def execute(self, context: SkillContext) -> SkillResult: ...

    async def get_spi_client(self, tenant_id: str) -> LocalDbSpiAdapter:
        """获取租户 SPI 客户端。TODO(Phase 1b):remote/mcp 模式适配器,当前统一本地适配器。"""
        return LocalDbSpiAdapter()
