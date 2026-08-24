import { Body, Controller, Get, Param, Patch, Query, UseGuards } from '@nestjs/common';
import { IsBoolean, IsNumber, IsOptional, IsString } from 'class-validator';
import { CurrentTenant, TenantGuard } from '../../common/guards/tenant.guard';
import type { TenantContextPayload } from '../../common/tenant/tenant.context';
import { SkillsService } from './skills.service';

export class UpdateTenantSkillDto {
  @IsOptional()
  @IsBoolean()
  enabled?: boolean;

  @IsOptional()
  @IsNumber()
  approvalThresholdAmount?: number;

  @IsOptional()
  @IsString()
  customPolicyPrompt?: string;
}

@Controller('api/skills')
export class SkillsController {
  constructor(private readonly skillsService: SkillsService) {}

  /**
   * 获取全局注册的所有技能列表
   */
  @Get('registry')
  getRegistry() {
    return {
      success: true,
      skills: this.skillsService.getAllSkills(),
    };
  }

  /**
   * 获取租户视角下的技能状态与阈值配置
   */
  @Get('tenant')
  @UseGuards(TenantGuard)
  async getTenantSkills(@CurrentTenant() tenant: TenantContextPayload) {
    const skills = await this.skillsService.getTenantSkills(tenant.tenantId);
    return {
      success: true,
      tenantId: tenant.tenantId,
      skills,
    };
  }

  /**
   * 更新指定租户的技能参数与风控阈值
   */
  @Patch('tenant/:skillId')
  @UseGuards(TenantGuard)
  async updateTenantSkill(
    @CurrentTenant() tenant: TenantContextPayload,
    @Param('skillId') skillId: string,
    @Body()
    body: UpdateTenantSkillDto,
  ) {
    const updated = await this.skillsService.updateTenantSkillConfig(tenant.tenantId, skillId, body);
    return {
      success: true,
      tenantId: tenant.tenantId,
      skillId,
      config: updated,
    };
  }
}
