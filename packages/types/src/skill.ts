/**
 * 业务技能与标准 SOP 层定义 (Agent Skill / SOP Layer)
 * 封装高阶业务决策逻辑（生鲜售后、极速改地址、售前导购推荐等）
 */

import type { RichCardBlock } from './card';

export interface SkillMetadata {
  id: string;
  name: string;
  description: string;
  category: 'after_sale' | 'pre_sale' | 'logistics' | 'general';
  triggerIntents: string[];
  requiredTools: string[];
  requiresApproval?: boolean;
  approvalThresholdAmount?: number;
  version?: string;
}

export interface SkillExecutionContext {
  threadId: string;
  tenantId: string;
  userId?: string;
  userEmail?: string;
  input: string;
  slots: Record<string, unknown>;
  userProfile?: {
    tags?: string[];
    preferences?: Record<string, unknown>;
    memberLevel?: string;
  };
  imageUrls?: string[];
  extra?: Record<string, unknown>;
}

export interface SkillExecutionResult {
  success: boolean;
  skillId: string;
  output: string;
  cards?: RichCardBlock[];
  updatedSlots?: Record<string, unknown>;
  nextAction?: 'finish' | 'human_takeover' | 'require_approval' | 'replan';
  approvalPayload?: {
    actionType: string;
    amount?: number;
    reason?: string;
    details?: Record<string, unknown>;
  };
  error?: string;
}

export interface AgentSkill {
  metadata: SkillMetadata;
  canHandle(context: SkillExecutionContext): boolean | Promise<boolean>;
  validatePreconditions?(context: SkillExecutionContext): Promise<{ valid: boolean; missingPrompt?: string }>;
  execute(context: SkillExecutionContext): Promise<SkillExecutionResult>;
}
