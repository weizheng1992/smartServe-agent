import type { Approval } from 'types';

export type ApprovalCategory = 'refund' | 'address' | 'human' | 'generic';

export interface ApprovalContextData {
  category: ApprovalCategory;
  orderId?: string;
  refundAmount?: number | string;
  oldAddress?: string;
  newAddress?: string;
  recipientName?: string;
  phone?: string;
  reason?: string;
  userInput?: string;
  triggerSource?: string;
  extraArgs: Record<string, unknown>;
}

export function getApprovalCategory(actionType?: string): ApprovalCategory {
  if (!actionType) return 'generic';
  const lower = actionType.toLowerCase();

  if (lower.includes('refund') || lower.includes('processrefund') || lower.includes('order_refund')) {
    return 'refund';
  }

  if (
    lower.includes('address') ||
    lower.includes('changeshippingaddress') ||
    lower.includes('modify_address') ||
    lower.includes('shipping')
  ) {
    return 'address';
  }

  if (lower.includes('human') || lower.includes('escalat') || lower.includes('transfer')) {
    return 'human';
  }

  return 'generic';
}

export function getApprovalContextData(approval: Approval): ApprovalContextData {
  const category = getApprovalCategory(approval.actionType);
  const payload = (approval.actionPayload || {}) as Record<string, unknown>;
  const args = ((payload.args as Record<string, unknown>) || {}) as Record<string, unknown>;

  const orderId = (payload.orderId as string) || (args.orderId as string) || (args.order_id as string) || undefined;

  const refundAmount =
    (payload.refundAmount as number | string) ||
    (payload.amount as number | string) ||
    (args.refundAmount as number | string) ||
    (args.amount as number | string) ||
    undefined;

  const oldAddress =
    (payload.oldAddress as string) ||
    (payload.previousAddress as string) ||
    (args.oldAddress as string) ||
    (args.previousAddress as string) ||
    undefined;

  const newAddress =
    (payload.newAddress as string) ||
    (payload.address as string) ||
    (args.newAddress as string) ||
    (args.address as string) ||
    undefined;

  const recipientName =
    (payload.recipientName as string) ||
    (payload.recipient as string) ||
    (args.recipientName as string) ||
    (args.recipient as string) ||
    (args.name as string) ||
    undefined;

  const phone =
    (payload.phone as string) ||
    (payload.telephone as string) ||
    (args.phone as string) ||
    (args.telephone as string) ||
    undefined;

  const reason =
    approval.reason ||
    (payload.reason as string) ||
    (payload.rejectionReason as string) ||
    (args.reason as string) ||
    (payload.description as string) ||
    undefined;

  const userInput =
    (payload.userInput as string) ||
    (payload.userMessage as string) ||
    (args.userInput as string) ||
    (args.userMessage as string) ||
    undefined;

  const triggerSource = (payload.triggerSource as string) || (args.triggerSource as string) || undefined;

  // Filter out extracted keys from extraArgs
  const extractedKeys = new Set([
    'orderId',
    'order_id',
    'refundAmount',
    'amount',
    'oldAddress',
    'previousAddress',
    'newAddress',
    'address',
    'recipientName',
    'recipient',
    'name',
    'phone',
    'telephone',
    'reason',
    'userInput',
    'userMessage',
    'triggerSource',
    'description',
  ]);

  const extraArgs: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(args)) {
    if (!extractedKeys.has(k) && v !== undefined && v !== null) {
      extraArgs[k] = v;
    }
  }

  return {
    category,
    orderId,
    refundAmount,
    oldAddress,
    newAddress,
    recipientName,
    phone,
    reason,
    userInput,
    triggerSource,
    extraArgs,
  };
}
