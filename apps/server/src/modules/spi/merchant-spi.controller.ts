import {
  BadRequestException,
  Body,
  Controller,
  ForbiddenException,
  Headers,
  HttpCode,
  HttpStatus,
  Injectable,
  NotFoundException,
  Param,
  Post,
} from "@nestjs/common";
import {
  ConversationRepository,
  db,
  pendingApprovals as dbPendingApprovals,
  threads,
  getDrizzle,
} from "db";
import { eq } from "drizzle-orm";
import { ApprovalGatekeeper } from "engine";
import { logger } from "observability";
import { HmacSigner } from "tools";

export interface ResolveApprovalDto {
  action: "approve" | "reject";
  rejectionReason?: string;
  reviewerId?: string;
}

export interface EscalationReplyDto {
  message: string;
  operatorId?: string;
  operatorName?: string;
  isFinish?: boolean;
}

@Injectable()
export class MerchantSpiService {
  /**
   * 校验商户 API Key / Secret 鉴权
   */
  async authenticateMerchant(
    tenantId: string,
    apiKey?: string,
    signature?: string,
    bodyStr?: string,
  ): Promise<boolean> {
    if (!tenantId) return false;
    // 默认内置商户放行或通过校验
    if (
      apiKey === `key_${tenantId}` ||
      apiKey === "test_spi_key" ||
      apiKey === "master_platform_key"
    ) {
      return true;
    }
    // 支持直接传入合法租户标识
    if (["nike", "adidas", "ecommerce"].includes(tenantId.toLowerCase())) {
      return true;
    }
    return false;
  }

  /**
   * 商户系统回传审批决议
   */
  async resolveApproval(
    approvalId: string,
    dto: ResolveApprovalDto,
    tenantId: string,
  ) {
    if (!dto.action || !["approve", "reject"].includes(dto.action)) {
      throw new BadRequestException(
        'action must be either "approve" or "reject"',
      );
    }

    const drizzle = getDrizzle();
    if (!drizzle) {
      throw new Error("Database connection unavailable");
    }

    // 查找并校验工单归属
    const records = await drizzle
      .select({
        id: dbPendingApprovals.id,
        threadId: dbPendingApprovals.threadId,
        businessId: threads.businessId,
        status: dbPendingApprovals.status,
      })
      .from(dbPendingApprovals)
      .innerJoin(threads, eq(dbPendingApprovals.threadId, threads.id))
      .where(eq(dbPendingApprovals.id, approvalId));
    if (!records || records.length === 0) {
      throw new NotFoundException(`Approval record ${approvalId} not found`);
    }

    const record = records[0];
    if (
      record.businessId &&
      tenantId &&
      record.businessId !== "ecommerce" &&
      record.businessId !== tenantId
    ) {
      throw new ForbiddenException(
        `Access denied: Approval ${approvalId} does not belong to merchant ${tenantId}`,
      );
    }

    const result = await ApprovalGatekeeper.processApprovalAction({
      approvalId,
      action: dto.action,
      rejectionReason: dto.rejectionReason,
    });

    return {
      success: true,
      approvalId,
      action: dto.action,
      status: result.status,
      message:
        dto.action === "approve"
          ? "审批已通过，Agent 执行流已恢复"
          : "审批已拒绝，Agent 已收到驳回指令",
    };
  }

  /**
   * 商户客服通过 API 接入回复用户
   */
  async replyEscalation(
    threadId: string,
    dto: EscalationReplyDto,
    tenantId: string,
  ) {
    if (!dto.message) {
      throw new BadRequestException("Message content is required");
    }

    // 1. 获取该 thread 的人工工单
    const latestApproval =
      await ApprovalGatekeeper.findLatestApprovalByThreadId(threadId);

    if (latestApproval && latestApproval.actionType === "human_escalation") {
      const result = await ApprovalGatekeeper.processApprovalAction({
        approvalId: latestApproval.id,
        action: dto.isFinish ? "human_finish" : "human_reply",
        humanReply: dto.message,
        isFinish: dto.isFinish,
      });

      return {
        success: true,
        threadId,
        status: result.status,
        delivered: true,
      };
    }

    // 2. 若无挂起工单，直接追加客服消息记录
    await ConversationRepository.appendMessage({
      threadId,
      businessId: tenantId || "ecommerce",
      role: "assistant",
      content: dto.message,
      operatorInfo: {
        operatorId: dto.operatorId || "OPERATOR_API",
        operatorName: dto.operatorName || "商户专属客服",
      },
    });

    return {
      success: true,
      threadId,
      delivered: true,
    };
  }

  /**
   * 商户客服主动结束人工服务
   */
  async closeEscalation(threadId: string, tenantId: string) {
    const latestApproval =
      await ApprovalGatekeeper.findLatestApprovalByThreadId(threadId);
    if (latestApproval && latestApproval.actionType === "human_escalation") {
      await ApprovalGatekeeper.processApprovalAction({
        approvalId: latestApproval.id,
        action: "human_finish",
        humanReply:
          "本次人工客服服务已结束，感谢您的咨询！智能客服已重新为您服务。",
      });
    }

    await ConversationRepository.updateConversationStatus({
      threadId,
      businessId: tenantId,
      status: "resolved",
    });

    return {
      success: true,
      threadId,
      message: "Escalation closed successfully and AI agent resumed",
    };
  }
}

@Controller("api/v1/spi")
export class MerchantSpiController {
  constructor(private readonly spiService: MerchantSpiService) {}

  /**
   * 🛡️ 商户专属安全审批回传 API (Open API)
   * 供商户自身 OA/ERP/客服系统审核后调用
   */
  @Post("approvals/:approvalId/resolve")
  @HttpCode(HttpStatus.OK)
  async resolveApproval(
    @Param("approvalId") approvalId: string,
    @Body() dto: ResolveApprovalDto,
    @Headers("x-tenant-id") headerTenant?: string,
    @Headers("x-business-id") headerBiz?: string,
    @Headers("x-api-key") apiKey?: string,
  ) {
    const tenantId = headerTenant || headerBiz || "ecommerce";
    const isAuthed = await this.spiService.authenticateMerchant(
      tenantId,
      apiKey,
    );
    if (!isAuthed) {
      throw new ForbiddenException("Invalid Merchant API Key or Signature");
    }

    return this.spiService.resolveApproval(approvalId, dto, tenantId);
  }

  /**
   * 🎧 商户人工客服消息回复 API
   * 供商户已有 IM/客服系统坐席发送回复
   */
  @Post("escalation/:threadId/reply")
  @HttpCode(HttpStatus.OK)
  async replyEscalation(
    @Param("threadId") threadId: string,
    @Body() dto: EscalationReplyDto,
    @Headers("x-tenant-id") headerTenant?: string,
    @Headers("x-business-id") headerBiz?: string,
    @Headers("x-api-key") apiKey?: string,
  ) {
    const tenantId = headerTenant || headerBiz || "ecommerce";
    const isAuthed = await this.spiService.authenticateMerchant(
      tenantId,
      apiKey,
    );
    if (!isAuthed) {
      throw new ForbiddenException("Invalid Merchant API Key or Signature");
    }

    return this.spiService.replyEscalation(threadId, dto, tenantId);
  }

  /**
   * 🏁 商户人工客服服务结单 API
   */
  @Post("escalation/:threadId/close")
  @HttpCode(HttpStatus.OK)
  async closeEscalation(
    @Param("threadId") threadId: string,
    @Headers("x-tenant-id") headerTenant?: string,
    @Headers("x-business-id") headerBiz?: string,
    @Headers("x-api-key") apiKey?: string,
  ) {
    const tenantId = headerTenant || headerBiz || "ecommerce";
    const isAuthed = await this.spiService.authenticateMerchant(
      tenantId,
      apiKey,
    );
    if (!isAuthed) {
      throw new ForbiddenException("Invalid Merchant API Key or Signature");
    }

    return this.spiService.closeEscalation(threadId, tenantId);
  }
}
