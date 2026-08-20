'use client';

import React, { useState } from 'react';

// Local Hooks
import { useAdminDashboardData } from './hooks';

// Local Components
import { Header } from './components/Header';
import { HistoricalAudits } from './components/HistoricalAudits';
import { HumanChatModal } from './components/HumanChatModal';
import { Metrics } from './components/Metrics';
import { PendingApprovals } from './components/PendingApprovals';
import { PersonaAudit } from './components/PersonaAudit';
import type { Approval } from './hooks/types';

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
    handleHumanReplyAction,
    handlePreferenceAction,
    startActiveTakeover,
    pendingApprovals,
    auditedApprovals,
    preferences,
  } = useAdminDashboardData();

  const [activeChatApproval, setActiveChatApproval] = useState<Approval | null>(null);

  const handleStartTakeover = async () => {
    const approval = await startActiveTakeover('default_thread');
    if (approval) {
      setActiveChatApproval(approval);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans antialiased">
      {/* 🚀 Header */}
      <Header
        selectedMerchant={selectedMerchant}
        setSelectedMerchant={setSelectedMerchant}
        isRefreshing={isRefreshing}
        fetchDashboardData={fetchDashboardData}
        onStartActiveTakeover={handleStartTakeover}
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
          handleHumanReplyAction={handleHumanReplyAction}
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

      {/* 💬 Active Takeover IM Chat Modal */}
      <HumanChatModal
        approval={activeChatApproval}
        isOpen={Boolean(activeChatApproval)}
        onClose={() => setActiveChatApproval(null)}
        onSendReply={async (approvalId, replyMsg, isFinish) => {
          await handleHumanReplyAction(approvalId, replyMsg, isFinish);
        }}
      />
    </div>
  );
}
