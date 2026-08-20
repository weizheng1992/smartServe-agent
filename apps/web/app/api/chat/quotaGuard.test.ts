import { describe, expect, test } from 'bun:test';
import { checkTenantQuotaGuard, recordTokenUsage } from './quotaGuard';

describe('QuotaGuard Unit Tests', () => {
  test('Should allow requests within threshold', async () => {
    const res = await checkTenantQuotaGuard('test_quota_user_1', 'tenant_a');
    expect(res.allowed).toBe(true);
    expect(res.remainingRequests).toBeGreaterThan(0);
  });

  test('Should block when token usage exceeds max daily quota', async () => {
    // Record 600,000 tokens (exceeding 500,000 threshold)
    await recordTokenUsage('test_quota_user_heavy', 600000, 'tenant_b');

    const res = await checkTenantQuotaGuard('test_quota_user_heavy', 'tenant_b');
    expect(res.allowed).toBe(false);
    expect(res.reason).toContain('Token');
  });
});
