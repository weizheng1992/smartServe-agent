import type { AgentSkill, SkillExecutionContext } from "types";
import { CartManageSkill } from "./cartManageSkill";
import { OrderAddressModificationSkill } from "./orderAddressModificationSkill";
import { OrderRefundSkill } from "./orderRefundSkill";
import { ProductInquirySkill } from "./productInquirySkill";
import { ShoppingGuideSkill } from "./shoppingGuideSkill";

export class SkillRegistry {
  private static readonly skills = new Map<string, AgentSkill>();

  static {
    // 注册内置标准业务 SOP Skills
    SkillRegistry.register(new OrderAddressModificationSkill());
    SkillRegistry.register(new OrderRefundSkill());
    SkillRegistry.register(new ProductInquirySkill());
    SkillRegistry.register(new ShoppingGuideSkill());
    SkillRegistry.register(new CartManageSkill());
  }

  /**
   * 注册新 Skill
   */
  public static register(skill: AgentSkill): void {
    SkillRegistry.skills.set(skill.metadata.id, skill);
  }

  /**
   * 获取指定 ID 的 Skill
   */
  public static getSkill(skillId: string): AgentSkill | undefined {
    return SkillRegistry.skills.get(skillId);
  }

  /**
   * 获取所有已注册的 Skills
   */
  public static getAllSkills(): AgentSkill[] {
    return Array.from(SkillRegistry.skills.values());
  }

  /**
   * 根据当前执行上下文自动匹配最佳承接 Skill
   */
  public static findMatchingSkill(
    context: SkillExecutionContext,
  ): AgentSkill | null {
    const allSkills = Array.from(SkillRegistry.skills.values());
    for (const skill of allSkills) {
      if (skill.canHandle(context)) {
        return skill;
      }
    }
    return null;
  }
}
