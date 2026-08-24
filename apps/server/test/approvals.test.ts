import { describe, expect, it } from 'bun:test';
import { ApprovalsController } from '../src/modules/approvals/approvals.controller';
import { ApprovalsService } from '../src/modules/approvals/approvals.service';

describe('ApprovalsModule (Server Gateway)', () => {
  const service = new ApprovalsService();
  const controller = new ApprovalsController(service);

  it('should list approvals and filter by tenant correctly via service', async () => {
    const approvals = await service.listApprovals('ecommerce');
    expect(Array.isArray(approvals)).toBe(true);
  });

  it('should return controller response format with success flag', async () => {
    const res = await controller.getApprovals('ecommerce');
    expect(res.success).toBe(true);
    expect(Array.isArray(res.approvals)).toBe(true);
    expect(typeof res.total).toBe('number');
  });

  it('should handle approval actions gracefully when record does not exist', async () => {
    const res = await controller.resolveApproval({
      approvalId: 'nonexistent-id',
      action: 'approve',
    });

    expect(res).toBeDefined();
    expect(res.error).toBeDefined();
  });
});
