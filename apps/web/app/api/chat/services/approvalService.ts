import { ApprovalGatekeeper, type ProcessApprovalActionOptions, type ProcessApprovalActionResult } from 'engine';

export type { ProcessApprovalActionOptions, ProcessApprovalActionResult };

export async function listPendingApprovals() {
  return ApprovalGatekeeper.listPendingApprovals();
}

export async function processApprovalAction(
  options: ProcessApprovalActionOptions,
): Promise<ProcessApprovalActionResult> {
  return ApprovalGatekeeper.processApprovalAction(options);
}

export const ApprovalService = {
  listPendingApprovals,
  processApprovalAction,
};
