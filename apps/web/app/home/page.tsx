'use client';

import { useEffect, useRef } from 'react';
import { Button, Card, CardContent, CardFooter, CardHeader, CardTitle, ImageIcon, Loader2, X } from 'ui';

// Local Hooks
import { useApprovals, useAuth, useChatMessages, useChatThreads } from './hooks';

import { APMPanel } from './components/APMPanel';
import { AuditDesk } from './components/AuditDesk';
import { ChatArea } from './components/ChatArea';
// Local Components
import { LeftSidebar } from './components/LeftSidebar';

// Safely format timestamps into MM-DD HH:mm format without hydration mismatches or invalid parsing
const formatFriendlyDate = (dateStr: string | Date | undefined | null) => {
  if (!dateStr) return '未知时间';
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return '未知时间';

  const pad = (n: number) => String(n).padStart(2, '0');
  const month = pad(d.getMonth() + 1);
  const date = pad(d.getDate());
  const hours = pad(d.getHours());
  const minutes = pad(d.getMinutes());

  return `${month}-${date} ${hours}:${minutes}`;
};

export default function Home() {
  const { currentUser, isPageHydrated, handleLogout } = useAuth();

  const {
    threads,
    setThreads,
    activeThreadId,
    setActiveThreadId,
    selectedNewThreadMerchant,
    setSelectedNewThreadMerchant,
    isThreadsLoading,
    fetchThreads,
    handleCreateNewThread,
    handleMerchantSwitch,
    handleDeleteThread,
  } = useChatThreads({
    currentUser,
    onThreadCreated: () => {
      setRunningDetails([]);
      setActivePlan(null);
      setCurrentStepText('');
    },
  });

  const {
    messages,
    setMessages,
    input,
    setInput,
    isSubmitting,
    setIsSubmitting,
    activePlan,
    setActivePlan,
    currentStepText,
    setCurrentStepText,
    selectedScreenshot,
    setSelectedScreenshot,
    tokensConsumed,
    setTokensConsumed,
    runningDetails,
    setRunningDetails,
    syncPollCountRef,
    loadHistory,
    triggerStream,
    handleSend,
  } = useChatMessages({
    currentUser,
    activeThreadId,
    fetchThreads,
  });

  const {
    allApprovals,
    pendingApprovalsList,
    rejectionInput,
    setRejectionReason,
    activeTab,
    setActiveTab,
    selectedApprovalId,
    setSelectedApprovalId,
    auditFilter,
    setAuditFilter,
    handleApprovalAction,
  } = useApprovals({
    currentUser,
    activeThreadId,
    loadHistory,
    fetchThreads,
    syncPollCountRef,
    setMessages,
    setIsSubmitting,
    triggerStream,
  });

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 🌟 Auto Scroll to Bottom effect
  useEffect(() => {
    if (messages.length > 0) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  // 首屏渲染占位符，防止重定向闪烁
  if (!isPageHydrated || !currentUser) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-slate-950 text-slate-100 font-sans">
        <div className="flex flex-col items-center gap-3.5">
          <Loader2 className="h-9 w-9 animate-spin text-indigo-500" />
          <span className="text-xs font-mono text-slate-500 tracking-wider uppercase">
            Loading Workspace Session...
          </span>
        </div>
      </div>
    );
  }

  // ================= 2. 主会话大屏控制台 =================
  return (
    <div className="flex h-screen bg-slate-950 text-slate-100 font-sans overflow-hidden">
      {/* 🚀 左侧：全新的历史对话与会话管理面板 */}
      <LeftSidebar
        currentUser={currentUser}
        threads={threads}
        activeThreadId={activeThreadId}
        setActiveThreadId={setActiveThreadId}
        selectedNewThreadMerchant={selectedNewThreadMerchant}
        setSelectedNewThreadMerchant={setSelectedNewThreadMerchant}
        isThreadsLoading={isThreadsLoading}
        isSubmitting={isSubmitting}
        allApprovals={allApprovals}
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        handleCreateNewThread={handleCreateNewThread}
        handleDeleteThread={handleDeleteThread}
        handleMerchantSwitch={handleMerchantSwitch}
        handleLogout={handleLogout}
        formatFriendlyDate={formatFriendlyDate}
      />

      {/* 中右侧大屏 */}
      <div className="flex-1 flex flex-col md:flex-row h-full overflow-hidden">
        {activeTab === 'CHAT_DESK' ? (
          <>
            {/* Chatting window */}
            <ChatArea
              activeThreadId={activeThreadId}
              messages={messages}
              input={input}
              setInput={setInput}
              isSubmitting={isSubmitting}
              loadHistory={loadHistory}
              handleSend={handleSend}
              setActivePlan={setActivePlan}
              setCurrentStepText={setCurrentStepText}
              setRunningDetails={setRunningDetails}
              setSelectedScreenshot={setSelectedScreenshot}
              messagesEndRef={messagesEndRef}
            />

            {/* Right Execution Detail Logging Panel */}
            <APMPanel
              tokensConsumed={tokensConsumed}
              pendingApprovalsList={pendingApprovalsList}
              rejectionInput={rejectionInput}
              setRejectionReason={setRejectionReason}
              runningDetails={runningDetails}
              activePlan={activePlan}
              handleApprovalAction={handleApprovalAction}
            />
          </>
        ) : (
          /* 🛡️ smartServe 客服大盘核签与安全中心 */
          <AuditDesk
            currentUser={currentUser}
            allApprovals={allApprovals}
            selectedApprovalId={selectedApprovalId}
            setSelectedApprovalId={setSelectedApprovalId}
            auditFilter={auditFilter}
            setAuditFilter={setAuditFilter}
            rejectionInput={rejectionInput}
            setRejectionReason={setRejectionReason}
            isSubmitting={isSubmitting}
            handleApprovalAction={handleApprovalAction}
            setActiveTab={setActiveTab}
          />
        )}
      </div>

      {/* 📸 Fullscreen Screenshot Viewer Modal */}
      {selectedScreenshot && (
        <div className="fixed inset-0 bg-slate-950/95 backdrop-blur-md z-50 flex items-center justify-center p-6">
          <Card className="bg-slate-900 border-slate-800 max-w-4xl w-full overflow-hidden shadow-2xl">
            <CardHeader className="px-6 py-4 border-b border-slate-800 flex flex-row justify-between items-center space-y-0">
              <div className="flex items-center space-x-2.5">
                <ImageIcon className="h-4.5 w-4.5 text-indigo-400" />
                <CardTitle className="text-sm font-semibold text-slate-200">网页看板・快照渲染核验大图</CardTitle>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setSelectedScreenshot(null)}
                className="h-8 w-8 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg"
              >
                <X className="h-4.5 w-4.5" />
              </Button>
            </CardHeader>
            <CardContent className="p-6 bg-slate-950 flex items-center justify-center min-h-[350px]">
              <img
                src={selectedScreenshot}
                alt="Viewport Verification"
                className="max-h-[60vh] rounded-lg border border-slate-800 shadow-2xl object-contain bg-slate-900"
              />
            </CardContent>
            <CardFooter className="px-6 py-3 border-t border-slate-800 flex justify-end">
              <Button onClick={() => setSelectedScreenshot(null)} variant="secondary" size="sm">
                关闭大图
              </Button>
            </CardFooter>
          </Card>
        </div>
      )}
    </div>
  );
}
