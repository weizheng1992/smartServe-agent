import { TenantRegistryService } from 'business-configs';
import { SpiConnectorFactory, type ThirdPartySpiClient } from 'tools';
import type { AgentSkill, SkillExecutionContext, SkillExecutionResult, SkillMetadata } from 'types';

export abstract class BaseSkill implements AgentSkill {
  public abstract metadata: SkillMetadata;

  /**
   * 判断当前上下文是否由该 Skill 承接
   */
  public canHandle(context: SkillExecutionContext): boolean {
    const activeIntent = (context.slots?.activeIntent as string) || '';
    return this.metadata.triggerIntents.includes(activeIntent);
  }

  /**
   * 前置必要槽位或业务条件校验
   */
  public async validatePreconditions?(
    context: SkillExecutionContext,
  ): Promise<{ valid: boolean; missingPrompt?: string }>;

  /**
   * 核心业务 SOP 执行实现
   */
  public abstract execute(context: SkillExecutionContext): Promise<SkillExecutionResult>;

  /**
   * 快捷获取当前租户对应的 SPI 客户端 (动态适配本地 DB 或远程第三方 SPI)
   */
  protected async getSpiClient(tenantId: string): Promise<ThirdPartySpiClient> {
    const config = await TenantRegistryService.getTenantConfig(tenantId);
    return SpiConnectorFactory.getClient(config.spiConnector, tenantId);
  }
}
