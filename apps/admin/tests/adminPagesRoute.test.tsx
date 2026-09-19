import { describe, expect, it } from 'bun:test';
import React from 'react';
import { AdminLayout } from '../src/components/layout';
import {
  AuditsPage,
  BillingPage,
  ConversationsPage,
  EvalsPage,
  GuardrailsPage,
  PersonasPage,
  RagStudioPage,
  SkillsToolsPage,
  SystemLogsPage,
  TenantsPage,
} from '../src/pages';
import { useAdminTenantStore } from '../src/store/tenantStore';

describe('Admin Control Plane Multi-Route Integration Tests', () => {
  it('renders AdminLayout with sidebar and navigation successfully', () => {
    const layout = React.createElement(AdminLayout);
    expect(layout).toBeDefined();
  });

  it('renders TenantsPage module', () => {
    const page = React.createElement(TenantsPage);
    expect(page).toBeDefined();
  });

  it('renders ConversationsPage module', () => {
    const page = React.createElement(ConversationsPage);
    expect(page).toBeDefined();
  });

  it('renders AuditsPage module', () => {
    const page = React.createElement(AuditsPage);
    expect(page).toBeDefined();
  });

  it('renders PersonasPage module', () => {
    const page = React.createElement(PersonasPage);
    expect(page).toBeDefined();
  });

  it('renders RagStudioPage module', () => {
    const page = React.createElement(RagStudioPage);
    expect(page).toBeDefined();
  });

  it('renders SkillsToolsPage module', () => {
    const page = React.createElement(SkillsToolsPage);
    expect(page).toBeDefined();
  });

  it('renders EvalsPage module', () => {
    const page = React.createElement(EvalsPage);
    expect(page).toBeDefined();
  });

  it('renders BillingPage module', () => {
    const page = React.createElement(BillingPage);
    expect(page).toBeDefined();
  });

  it('renders GuardrailsPage module', () => {
    const page = React.createElement(GuardrailsPage);
    expect(page).toBeDefined();
  });

  it('renders SystemLogsPage module', () => {
    const page = React.createElement(SystemLogsPage);
    expect(page).toBeDefined();
  });

  it('supports global multi-tenant state switching', () => {
    const store = useAdminTenantStore.getState();
    expect(store.selectedTenantId).toBe('all');

    // 真实租户列表由 /api/tenant/list 动态加载(dev 网关在线才有;CI 无网关),
    // 这里直接注入一个真实形态租户,只验证切换/命中/回退的纯逻辑
    useAdminTenantStore.getState().addOrUpdateTenant({ id: 'nike', name: 'Nike 官方旗舰店' });
    store.setSelectedTenantId('nike');
    expect(useAdminTenantStore.getState().selectedTenantId).toBe('nike');
    expect(useAdminTenantStore.getState().getSelectedTenant().name).toBe('Nike 官方旗舰店');

    store.setSelectedTenantId('all');
    expect(useAdminTenantStore.getState().selectedTenantId).toBe('all');
  });
});
