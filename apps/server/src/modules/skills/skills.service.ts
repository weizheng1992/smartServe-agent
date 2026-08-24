import { Injectable } from '@nestjs/common';
import { TenantRegistryService } from 'business-configs';
import { SkillRegistry } from 'engine';
import type { AgentSkill, TenantSkillConfig } from 'types';

@Injectable()
export class SkillsService {
  /**
   * 获取系统中已注册的所有业务技能元数据
   */
  getAllSkills(): AgentSkill['metadata'][] {
    return SkillRegistry.getAllSkills().map((s) => s.metadata);
  }

  /**
   * 获取指定租户生效的技能配置
   */
  async getTenantSkills(tenantId: string) {
    const config = await TenantRegistryService.getTenantConfig(tenantId);
    const allSkills = SkillRegistry.getAllSkills();

    return allSkills.map((skill) => {
      const tenantSkill = config.skillsConfig?.[skill.metadata.id];
      const isEnabled =
        tenantSkill?.enabled ?? (!config.enabledSkills || config.enabledSkills.includes(skill.metadata.id));
      const approvalThreshold = tenantSkill?.approvalThresholdAmount ?? skill.metadata.approvalThresholdAmount ?? 50;

      return {
        ...skill.metadata,
        enabled: isEnabled,
        effectiveApprovalThreshold: approvalThreshold,
        customPolicyPrompt: tenantSkill?.customPolicyPrompt,
      };
    });
  }

  /**
   * 更新或覆盖指定租户的技能配置
   */
  async updateTenantSkillConfig(tenantId: string, skillId: string, skillConfig: Partial<TenantSkillConfig>) {
    return TenantRegistryService.updateTenantSkillConfig(tenantId, skillId, skillConfig);
  }
}
