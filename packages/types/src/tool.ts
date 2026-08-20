import type { z } from 'zod';

export interface ToolExecutionArgs {
  threadId?: string;
  orderId?: string;
  reason?: string;
  amount?: string;
  newAddress?: string;
  url?: string;
  fullPage?: boolean;
  isApproved?: boolean;
  preferenceType?: string;
  preferenceValue?: string;
  [key: string]: unknown;
}

export interface ToolAuditTrail {
  approvalId: string;
  approvedAt: string;
  policyMatched: string;
  actionVerifier: string;
  verifiableHash: string;
}

export interface ToolExecutionResult {
  success?: boolean;
  error?: string;
  message?: string;
  orderId?: string;
  status?: string;
  totalAmount?: string;
  refundAmount?: string;
  newAddress?: string;
  invoiceId?: string;
  taxAmount?: string;
  auditTrail?: ToolAuditTrail | null;
  waitingForApproval?: boolean;
  actionType?: string;
  actionPayload?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ToolDefinition<
  TArgs extends Record<string, unknown> = ToolExecutionArgs,
  TResult = ToolExecutionResult,
> {
  name: string;
  description: string;
  schema: z.ZodObject<z.ZodRawShape>;
  execute: (args: TArgs) => Promise<TResult>;
}
