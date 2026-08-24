import { useState } from 'react';
import { HumanChatModal } from 'ui';

// Local Hooks & Components
import { ConversationsExplorer } from '../components/ConversationsExplorer';
import { Header } from '../components/Header';
import { HistoricalAudits } from '../components/HistoricalAudits';
import { LiveDesk } from '../components/LiveDesk';
import { Metrics } from '../components/Metrics';
import { PendingApprovals } from '../components/PendingApprovals';
import { PersonaAudit } from '../components/PersonaAudit';
import { useAdminDashboardData } from '../hooks';
import type { Approval } from '../hooks/types';

export function AdminDashboardPage() {
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

  const [activeTab, setActiveTab] = useState<'approvals' | 'conversations' | 'live-desk'>('approvals');
  const [liveDeskThreadId, setLiveDeskThreadId] = useState<string | undefined>(undefined);
  const [activeChatApproval, setActiveChatApproval] = useState<Approval | null>(null);

  const handleStartTakeover = async () => {
    const targetThread = pendingApprovals[0]?.threadId || auditedApprovals[0]?.threadId || 'default_thread';
    const approval = await startActiveTakeover(targetThread);
    if (approval) {
      setActiveChatApproval(approval);
    }
  };

  const handleSelectForLiveDesk = (threadId: string) => {
    setLiveDeskThreadId(threadId);
    setActiveTab('live-desk');
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans antialiased">
      {/* 🚀 Header */}
      <Header
        selectedMerchant={selectedMerchant}
        setSelectedMerchant={setSelectedMerchant}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        isRefreshing={isRefreshing}
        fetchDashboardData={fetchDashboardData}
        onStartActiveTakeover={handleStartTakeover}
      />

      <main className="p-8 max-w-7xl mx-auto space-y-8">
        {/* 📊 Section: Approvals & HITL Mode */}
        {activeTab === 'approvals' && (
          <>
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
              onOpenChatModal={(app) => setActiveChatApproval(app)}
            />

            {/* 🧠 Section 1.5: User Preferences & Persona Dynamic Audit Center */}
            <PersonaAudit
              selectedMerchant={selectedMerchant}
              preferences={preferences}
              handlePreferenceAction={handlePreferenceAction}
            />

            {/* 📁 Section 2: Historical Audited Records */}
            <HistoricalAudits auditedApprovals={auditedApprovals} />
          </>
        )}

        {/* 💬 Section: Full-Spectrum Multi-Tenant Conversations Explorer */}
        {activeTab === 'conversations' && (
          <ConversationsExplorer selectedMerchant={selectedMerchant} onSelectForLiveDesk={handleSelectForLiveDesk} />
        )}

        {/* ⚡ Section: Realtime Live Desk & Takeover Console */}
        {activeTab === 'live-desk' && (
          <LiveDesk selectedMerchant={selectedMerchant} initialThreadId={liveDeskThreadId} />
        )}
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
