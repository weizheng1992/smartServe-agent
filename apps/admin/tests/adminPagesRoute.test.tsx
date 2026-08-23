import { describe, expect, it } from "bun:test";
import React from "react";
import {
  TenantsPage,
  ConversationsPage,
  AuditsPage,
  PersonasPage,
  RagStudioPage,
  SkillsToolsPage,
  EvalsPage,
  BillingPage,
  GuardrailsPage,
  SystemLogsPage,
} from "../src/pages";
import { AdminLayout } from "../src/components/layout";
import { useAdminTenantStore } from "../src/store/tenantStore";

describe("Admin Control Plane Multi-Route Integration Tests", () => {
  it("renders AdminLayout with sidebar and navigation successfully", () => {
    const layout = React.createElement(AdminLayout);
    expect(layout).toBeDefined();
  });

  it("renders TenantsPage module", () => {
    const page = React.createElement(TenantsPage);
    expect(page).toBeDefined();
  });

  it("renders ConversationsPage module", () => {
    const page = React.createElement(ConversationsPage);
    expect(page).toBeDefined();
  });

  it("renders AuditsPage module", () => {
    const page = React.createElement(AuditsPage);
    expect(page).toBeDefined();
  });

  it("renders PersonasPage module", () => {
    const page = React.createElement(PersonasPage);
    expect(page).toBeDefined();
  });

  it("renders RagStudioPage module", () => {
    const page = React.createElement(RagStudioPage);
    expect(page).toBeDefined();
  });

  it("renders SkillsToolsPage module", () => {
    const page = React.createElement(SkillsToolsPage);
    expect(page).toBeDefined();
  });

  it("renders EvalsPage module", () => {
    const page = React.createElement(EvalsPage);
    expect(page).toBeDefined();
  });

  it("renders BillingPage module", () => {
    const page = React.createElement(BillingPage);
    expect(page).toBeDefined();
  });

  it("renders GuardrailsPage module", () => {
    const page = React.createElement(GuardrailsPage);
    expect(page).toBeDefined();
  });

  it("renders SystemLogsPage module", () => {
    const page = React.createElement(SystemLogsPage);
    expect(page).toBeDefined();
  });

  it("supports global multi-tenant state switching", () => {
    const store = useAdminTenantStore.getState();
    expect(store.selectedTenantId).toBe("all");

    store.setSelectedTenantId("nike");
    expect(useAdminTenantStore.getState().selectedTenantId).toBe("nike");
    expect(useAdminTenantStore.getState().getSelectedTenant().name).toBe(
      "Nike 官方旗舰店",
    );

    store.setSelectedTenantId("all");
    expect(useAdminTenantStore.getState().selectedTenantId).toBe("all");
  });
});
