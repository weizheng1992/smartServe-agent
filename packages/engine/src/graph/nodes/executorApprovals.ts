import { ApprovalGatekeeper, type CreateApprovalParams } from '../../approval/approvalGatekeeper';

export type { CreateApprovalParams };

export async function createPendingApprovalTicket(params: CreateApprovalParams) {
  return ApprovalGatekeeper.createPendingApprovalTicket(params);
}
