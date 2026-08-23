import { useCallback, useEffect, useState } from 'react';
import { useApprovalMachine } from 'ui';
import type { AnalyticsSummary, Approval, PreferenceFact } from './types';

export function useAdminDashboardData() {
  const [selectedMerchant, setSelectedMerchant] = useState<string>('ecommerce');
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [preferences, setPreferences] = useState<PreferenceFact[]>([]);
  const [summary, setSummary] = useState<AnalyticsSummary>({
    totalCostUsd: 0,
    totalSessions: 0,
    avgLatencyMs: 0,
    avgTokens: 0,
    autopilotRate: 100,
  });
  const [isRefreshing, setIsRefreshing] = useState(false);

  const { submittingActionId, rejectionReasons, setRejectionReasons, executeApprovalAction, executeHumanReplyAction } =
    useApprovalMachine();

  const fetchDashboardData = useCallback(async () => {
    setIsRefreshing(true);
    try {
      // 1. Fetch approvals list
      const appRes = await fetch('/api/chat/approvals');
      const appData = await appRes.json();
      if (appData.success && appData.approvals) {
        setApprovals(appData.approvals);
      }

      // 2. Fetch BI metrics for selected merchant
      const anaRes = await fetch(`/api/analytics?businessId=${selectedMerchant}`);
      const anaData = await anaRes.json();
      if (anaData.success && anaData.summary) {
        setSummary(anaData.summary);
      }

      // 3. Fetch user preference facts list
      const prefRes = await fetch('/api/chat/preferences');
      const prefData = await prefRes.json();
      if (prefData.success && prefData.preferences) {
        setPreferences(prefData.preferences);
      }
    } catch (err) {
      console.error('[Dashboard Fetch Error]:', err);
    } finally {
      setIsRefreshing(false);
    }
  }, [selectedMerchant]);

  useEffect(() => {
    fetchDashboardData();
    const interval = setInterval(fetchDashboardData, 5000); // Auto refresh every 5 seconds for high fidelity logs!
    return () => clearInterval(interval);
  }, [fetchDashboardData]);

  const handleApprovalAction = async (approvalId: string, action: 'approve' | 'reject') => {
    const result = await executeApprovalAction({
      approvalId,
      action,
    });
    if (result.success) {
      await fetchDashboardData();
    } else if (result.error) {
      alert(result.error);
    }
  };

  const handleHumanReplyAction = async (approvalId: string, replyMessage: string, isFinish = false) => {
    const result = await executeHumanReplyAction({
      approvalId,
      replyMessage,
      isFinish,
    });
    if (result.success) {
      await fetchDashboardData();
      return result.data;
    }
    if (result.error) {
      alert(result.error);
    }
  };

  const handlePreferenceAction = async (preferenceId: string, action: 'approve' | 'reject' | 'delete') => {
    try {
      const res = await fetch('/api/chat/preferences', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preferenceId, action }),
      });
      const data = await res.json();
      if (data.success) {
        await fetchDashboardData();
      } else {
        alert(data.error || '画像操作失败');
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      alert(`画像操作异常: ${errMsg}`);
    }
  };

  const startActiveTakeover = async (threadId = 'default_thread') => {
    try {
      const res = await fetch('/api/chat/approvals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'start_human_takeover',
          threadId,
        }),
      });
      const data = await res.json();
      if (data.success && data.approval) {
        await fetchDashboardData();
        return data.approval as Approval;
      }
      return null;
    } catch (err) {
      console.error('[Start Active Takeover Error]:', err);
      return null;
    }
  };

  // Filter approvals that are waiting or historical, matching the selected merchant
  const pendingApprovals = approvals.filter(
    (a) => a.status === 'waiting' && (a.businessId || 'ecommerce') === selectedMerchant,
  );
  const auditedApprovals = approvals.filter(
    (a) => a.status !== 'waiting' && (a.businessId || 'ecommerce') === selectedMerchant,
  );

  return {
    selectedMerchant,
    setSelectedMerchant,
    approvals,
    preferences,
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
  };
}
