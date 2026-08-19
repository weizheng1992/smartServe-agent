import type React from "react";
import {
  Avatar,
  AvatarFallback,
  Button,
  Loader2,
  LogOut,
  MessageSquare,
  Plus,
  Trash2,
} from "ui";
import type { PendingApprovalRecord } from "types";
import type { ChatThread, UserSession } from "../hooks/types";

interface LeftSidebarProps {
  currentUser: UserSession | null;
  threads: ChatThread[];
  activeThreadId: string;
  setActiveThreadId: (id: string) => void;
  selectedNewThreadMerchant: string;
  setSelectedNewThreadMerchant: (merchantId: string) => void;
  isThreadsLoading: boolean;
  isSubmitting: boolean;
  allApprovals: PendingApprovalRecord[];
  activeTab: "CHAT_DESK" | "AUDIT_DESK";
  setActiveTab: (tab: "CHAT_DESK" | "AUDIT_DESK") => void;
  handleCreateNewThread: (merchantId?: string) => Promise<void>;
  handleDeleteThread: (e: React.MouseEvent, id: string) => Promise<void>;
  handleMerchantSwitch: (merchantId: string) => Promise<void>;
  handleLogout: () => void;
  formatFriendlyDate: (dateStr: string | Date | undefined | null) => string;
}

export function LeftSidebar({
  currentUser,
  threads,
  activeThreadId,
  setActiveThreadId,
  selectedNewThreadMerchant,
  isThreadsLoading,
  isSubmitting,
  allApprovals,
  activeTab,
  setActiveTab,
  handleCreateNewThread,
  handleDeleteThread,
  handleMerchantSwitch,
  handleLogout,
  formatFriendlyDate,
}: LeftSidebarProps) {
  if (!currentUser) return null;

  return (
    <aside className="flex flex-col w-72 bg-slate-900 border-r border-slate-800 justify-between shrink-0">
      {/* 会话顶部账户卡片 */}
      <div className="p-4 border-b border-slate-800 bg-slate-950/20">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center space-x-2.5 min-w-0">
            <Avatar className="h-8.5 w-8.5 border border-indigo-500/30">
              <AvatarFallback className="bg-indigo-600 text-white text-xs font-mono">
                {currentUser.email.charAt(0).toUpperCase()}
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <p className="text-xs font-bold text-slate-200 truncate">
                {currentUser.email}
              </p>
              <div className="flex items-center gap-1 mt-0.5">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse shrink-0" />
                <span className="text-[9px] text-slate-500 font-mono uppercase tracking-wider">
                  Online
                </span>
              </div>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={handleLogout}
            className="h-7 w-7 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 shrink-0"
            title="登出账户"
          >
            <LogOut className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* 新增会话选择与操作按钮 */}
      <div className="px-4 pt-4 pb-2 space-y-2.5">
        <div className="flex flex-col gap-1.5">
          <span className="text-[9px] font-bold text-slate-500 uppercase tracking-wider font-mono px-1">
            选择对话商户
          </span>
          <div className="grid grid-cols-3 gap-1 bg-slate-950/60 border border-slate-850/80 p-1 rounded-xl">
            {[
              { id: "ecommerce", label: "主站" },
              { id: "nike", label: "Nike" },
              { id: "adidas", label: "Adidas" },
            ].map((m) => (
              <button
                type="button"
                key={m.id}
                onClick={() => handleMerchantSwitch(m.id)}
                className={`py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-wider transition ${
                  selectedNewThreadMerchant === m.id
                    ? "bg-indigo-600 text-white shadow-md"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-900/20"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>

        <Button
          onClick={() => handleCreateNewThread(selectedNewThreadMerchant)}
          className="w-full bg-slate-950/40 hover:bg-slate-950/80 text-indigo-400 border border-indigo-500/20 hover:border-indigo-500/40 rounded-xl h-10 text-xs font-semibold flex items-center justify-center gap-2 transition"
        >
          <Plus className="h-4 w-4" />
          <span>开启新一轮对话</span>
        </Button>
      </div>

      {/* Tab Switcher */}
      <div className="px-4 py-2 flex gap-2">
        <Button
          variant={activeTab === "CHAT_DESK" ? "default" : "outline"}
          onClick={() => setActiveTab("CHAT_DESK")}
          className={`flex-1 text-[11px] h-8 rounded-lg font-semibold transition ${
            activeTab === "CHAT_DESK"
              ? "bg-indigo-600 hover:bg-indigo-500 text-white border-transparent"
              : "border-slate-800 text-slate-400 hover:bg-slate-850 hover:text-slate-200 bg-transparent"
          }`}
        >
          💬 智能工作台
        </Button>
        <Button
          variant={activeTab === "AUDIT_DESK" ? "default" : "outline"}
          onClick={() => setActiveTab("AUDIT_DESK")}
          className={`flex-1 text-[11px] h-8 rounded-lg font-semibold transition relative ${
            activeTab === "AUDIT_DESK"
              ? "bg-indigo-600 hover:bg-indigo-500 text-white border-transparent"
              : "border-slate-800 text-slate-400 hover:bg-slate-850 hover:text-slate-200 bg-transparent"
          }`}
        >
          <span>🛡️ 审核中心</span>
          {allApprovals.filter((a) => a.status === "waiting").length > 0 && (
            <span className="absolute -top-1 -right-1 h-4.5 w-4.5 bg-rose-500 text-white text-[9px] rounded-full flex items-center justify-center font-bold animate-pulse">
              {allApprovals.filter((a) => a.status === "waiting").length}
            </span>
          )}
        </Button>
      </div>

      {/* 历史对话会话列表 */}
      <div className="flex-1 overflow-y-auto px-2 space-y-1.5 pt-2">
        <p className="text-[10px] font-bold text-slate-500 uppercase tracking-wider px-3 mb-1.5 font-mono">
          历史对话列表 ({threads.length})
        </p>

        {isThreadsLoading && threads.length === 0 ? (
          <div className="py-12 text-center flex flex-col items-center gap-2">
            <Loader2 className="h-5 w-5 animate-spin text-slate-600" />
            <span className="text-[10px] text-slate-500 font-mono">
              加载会话中...
            </span>
          </div>
        ) : threads.length === 0 ? (
          <div className="py-12 text-center px-4">
            <MessageSquare className="h-6 w-6 text-slate-700 mx-auto mb-2" />
            <p className="text-[11px] text-slate-500">
              无任何历史对话记录，点击上方按钮开辟一个吧！
            </p>
          </div>
        ) : (
          threads.map((t) => {
            const isActive = t.id === activeThreadId;

            return (
              // biome-ignore lint/a11y/useKeyWithClickEvents: Thread card is clickable for chat switching
              <div
                key={t.id}
                onClick={() => {
                  if (isSubmitting) return;
                  setActiveThreadId(t.id);
                }}
                className={`w-full text-left p-3 rounded-xl flex items-center justify-between gap-2.5 transition group border cursor-pointer ${
                  isActive
                    ? "bg-indigo-600/10 border-indigo-500/30 text-indigo-200 font-medium"
                    : "bg-transparent border-transparent text-slate-400 hover:bg-slate-950/30 hover:border-slate-800 hover:text-slate-200"
                }`}
              >
                <div className="flex items-center gap-2.5 min-w-0 flex-1">
                  <MessageSquare
                    className={`h-4.5 w-4.5 shrink-0 ${isActive ? "text-indigo-400" : "text-slate-600 group-hover:text-slate-400"}`}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-xs truncate font-mono tracking-tight">
                      {t.id}
                    </p>
                    <div className="flex items-center justify-between mt-1 text-[10px] text-slate-500">
                      <span className="font-mono">
                        {formatFriendlyDate(t.createdAt)}
                      </span>
                      <span
                        className={`px-1.5 py-0.2 rounded text-[8px] font-bold uppercase tracking-wider ${
                          t.businessId === "nike"
                            ? "bg-amber-500/10 text-amber-400 border border-amber-500/10"
                            : t.businessId === "adidas"
                              ? "bg-indigo-500/10 text-indigo-400 border border-indigo-500/10"
                              : "bg-slate-500/10 text-slate-400 border border-slate-800"
                        }`}
                      >
                        {t.businessId === "nike"
                          ? "Nike"
                          : t.businessId === "adidas"
                            ? "Adidas"
                            : "主站"}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Delete button, shows up on hover */}
                <button
                  type="button"
                  onClick={(e) => handleDeleteThread(e, t.id)}
                  className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 transition shrink-0"
                  title="删除会话"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            );
          })
        )}
      </div>

      {/* 底部探针参数 */}
      <div className="p-4 border-t border-slate-800/80 bg-slate-950/20">
        <div className="rounded-xl border border-slate-800/80 bg-slate-950/50 p-2.5 space-y-1">
          <span className="text-[8px] text-slate-500 font-mono tracking-widest uppercase block">
            PERSISTENT CACHE
          </span>
          <div className="flex items-center gap-1.5 text-[10px] text-slate-300 font-mono">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse shrink-0" />
            <span className="truncate">Local Storage Hydrated</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
