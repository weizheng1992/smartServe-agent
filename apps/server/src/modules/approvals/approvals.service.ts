import { Injectable } from '@nestjs/common';
import { ApprovalGatekeeper } from 'engine';
import { logger } from 'observability';
import type { PendingApprovalRecord } from 'types';

@Injectable()
export class ApprovalsService {
  /**
   * 拉取待审批工单列表（支持按租户过滤下推至 SQL）
   */
  async listApprovals(tenantId?: string, status?: string): Promise<PendingApprovalRecord[]> {
    try {
      return await ApprovalGatekeeper.listPendingApprovals({
        tenantId,
        status,
      });
    } catch (err) {
      logger.error({ err, tenantId }, '[ApprovalsService] Failed to list approvals');
      return [];
    }
  }

  /**
   * 处理审批决议动作（Approve / Reject / Cancel / Human Reply）
   */
  async resolveApproval(options: {
    approvalId?: string;
    threadId?: string;
    action: string;
    rejectionReason?: string;
    humanReply?: string;
    replyMessage?: string;
    isFinish?: boolean;
    tenantId?: string;
  }) {
    const { approvalId, threadId, action, rejectionReason, humanReply, replyMessage, isFinish } = options;

    logger.info({ approvalId, threadId, action, isFinish }, '[ApprovalsService] Processing approval action');

    const result = await ApprovalGatekeeper.processApprovalAction({
      approvalId,
      threadId,
      action,
      rejectionReason,
      humanReply: humanReply || replyMessage,
      isFinish,
    });

    return result;
  }
}
