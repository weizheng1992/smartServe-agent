"use client";

import React from "react";

// Local Hooks
import { useAdminDashboardData } from "./hooks";

// Local Components
import { Header } from "./components/Header";
import { Metrics } from "./components/Metrics";
import { PendingApprovals } from "./components/PendingApprovals";
import { PersonaAudit } from "./components/PersonaAudit";
import { HistoricalAudits } from "./components/HistoricalAudits";

export default function AdminDashboard() {
  const {
    selectedMerchant,
    setSelectedMerchant,
    summary,
    isRefreshing,
    rejectionReasons,
    setRejectionReasons,
    submittingActionId,
    fetchDashboardData,
    handleApprovalAction,
    handlePreferenceAction,
    pendingApprovals,
    auditedApprovals,
    preferences,
  } = useAdminDashboardData();

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans antialiased">
      {/* 🚀 Header */}
      <Header
        selectedMerchant={selectedMerchant}
        setSelectedMerchant={setSelectedMerchant}
        isRefreshing={isRefreshing}
        fetchDashboardData={fetchDashboardData}
      />

      <main className="p-8 max-w-7xl mx-auto space-y-8">
        {/* 📊 SaaS Telemetry BI Metrics Cards */}
        <Metrics summary={summary} />

        {/* 🛡️ Section 1: Active Pending Approvals Queue */}
        <PendingApprovals
          pendingApprovals={pendingApprovals}
          rejectionReasons={rejectionReasons}
          setRejectionReasons={setRejectionReasons}
          submittingActionId={submittingActionId}
          handleApprovalAction={handleApprovalAction}
        />

        {/* 🧠 Section 1.5: User Preferences & Persona Dynamic Audit Center */}
        <PersonaAudit
          selectedMerchant={selectedMerchant}
          preferences={preferences}
          handlePreferenceAction={handlePreferenceAction}
        />

        {/* 📁 Section 2: Historical Audited Records */}
        <HistoricalAudits auditedApprovals={auditedApprovals} />
      </main>
    </div>
  );
}
