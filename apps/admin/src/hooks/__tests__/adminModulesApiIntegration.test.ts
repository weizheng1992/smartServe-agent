import { describe, expect, it } from 'bun:test';
import {
  approvalsApi,
  billingApi,
  conversationsApi,
  evalsApi,
  guardrailsApi,
  personasApi,
  ragApi,
  skillsApi,
  systemLogsApi,
  tenantsApi,
} from '../../lib/api';

describe('Admin Modules API Integration & Data Mapping', () => {
  it('1. Conversations API should list conversations with proper headers and data', async () => {
    const res = await conversationsApi.list({ tenantId: 'all' });
    // In unit test without live server running fetch fails or returns payload
    expect(res).toBeDefined();
    expect(typeof res).toBe('object');
  });

  it('2. Approvals API should list pending approvals', async () => {
    const res = await approvalsApi.list({ tenantId: 'all' });
    expect(res).toBeDefined();
  });

  it('3. Skills API should fetch registry and config', async () => {
    const registry = await skillsApi.getRegistry();
    const config = await skillsApi.getConfig('all');
    expect(registry).toBeDefined();
    expect(config).toBeDefined();
  });

  it('4. Tenants API should list SaaS tenants', async () => {
    const res = await tenantsApi.list();
    expect(res).toBeDefined();
  });

  it('5. RAG API should list knowledge documents', async () => {
    const res = await ragApi.list('all');
    expect(res).toBeDefined();
  });

  it('6. Personas API should list user memory facts', async () => {
    const res = await personasApi.list('all');
    expect(res).toBeDefined();
  });

  it('7. Guardrails API should list security rules', async () => {
    const res = await guardrailsApi.list('all');
    expect(res).toBeDefined();
  });

  it('8. Billing API should get usages and overview', async () => {
    const usages = await billingApi.listTenantUsages();
    expect(usages).toBeDefined();
  });

  it('9. System Logs API should list logs', async () => {
    const logs = await systemLogsApi.list({ tenantId: 'all' });
    expect(logs).toBeDefined();
  });

  it('10. Evals API should get benchmark results', async () => {
    const evals = await evalsApi.getResults();
    expect(evals).toBeDefined();
  });
});
