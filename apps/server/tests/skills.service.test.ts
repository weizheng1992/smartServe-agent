import { describe, expect, it } from 'bun:test';
import { SkillsService } from '../src/modules/skills/skills.service';

describe('SkillsService NestJS Module', () => {
  const service = new SkillsService();

  it('should return all registered skills from SkillRegistry', () => {
    const skills = service.getAllSkills();
    expect(Array.isArray(skills)).toBe(true);
    expect(skills.length).toBeGreaterThanOrEqual(3);

    const refund = skills.find((s) => s.id === 'skill_order_refund');
    expect(refund).toBeDefined();
    expect(refund?.name).toBe('售后退款与理赔 SOP');
  });

  it('should retrieve tenant skill configs merged with global defaults', async () => {
    const tenantSkills = await service.getTenantSkills('ecommerce');
    expect(Array.isArray(tenantSkills)).toBe(true);
    expect(tenantSkills.length).toBeGreaterThanOrEqual(3);

    const refundSkill = tenantSkills.find((s) => s.id === 'skill_order_refund');
    expect(refundSkill).toBeDefined();
    expect(refundSkill?.enabled).toBe(true);
  });
});
