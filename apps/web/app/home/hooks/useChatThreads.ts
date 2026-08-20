import { useCallback, useEffect, useState } from 'react';
import type { ChatThread, UserSession } from './types';

interface UseChatThreadsProps {
  currentUser: UserSession | null;
  isSubmitting?: boolean;
  onThreadCreated?: () => void;
}

export function useChatThreads({ currentUser, isSubmitting = false, onThreadCreated }: UseChatThreadsProps) {
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string>('');
  const [selectedNewThreadMerchant, setSelectedNewThreadMerchant] = useState<string>('ecommerce');
  const [isThreadsLoading, setIsThreadsLoading] = useState(false);

  // 1. Read initial threadId from URL search parameters on page mount
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      const urlThreadId = params.get('threadId');
      if (urlThreadId) {
        setActiveThreadId(urlThreadId);
      }
    }
  }, []);

  // 2. Sync activeThreadId to URL search parameters whenever it changes
  useEffect(() => {
    if (activeThreadId && typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      if (params.get('threadId') !== activeThreadId) {
        params.set('threadId', activeThreadId);
        window.history.replaceState(null, '', `?${params.toString()}`);
      }
    }
  }, [activeThreadId]);

  // 3. Synchronize selected merchant tab highlighted in UI with the active thread's merchant
  useEffect(() => {
    if (activeThreadId && threads.length > 0) {
      const activeThread = threads.find((t) => t.id === activeThreadId);
      if (activeThread && activeThread.businessId) {
        setSelectedNewThreadMerchant(activeThread.businessId);
      }
    }
  }, [activeThreadId, threads]);

  // Fetch threads API
  const fetchThreads = useCallback(async () => {
    if (!currentUser) return;
    setIsThreadsLoading(true);
    try {
      const res = await fetch(`/api/chat/threads?userId=${currentUser.id}`);
      const data = await res.json();
      if (data.success && data.threads) {
        setThreads(data.threads);

        // Prioritize loading the active thread ID from the URL query parameter on load
        let queryActiveId = '';
        if (typeof window !== 'undefined') {
          const params = new URLSearchParams(window.location.search);
          queryActiveId = params.get('threadId') || '';
        }

        if (data.threads.length > 0) {
          setActiveThreadId((currentActiveId) => {
            const initialActiveId = queryActiveId || currentActiveId;
            if (initialActiveId && data.threads.some((t: ChatThread) => t.id === initialActiveId)) {
              return initialActiveId;
            }
            return data.threads[0].id;
          });
        }
      }
    } catch (err) {
      console.error('[Fetch Threads Error]:', err);
    } finally {
      setIsThreadsLoading(false);
    }
  }, [currentUser]);

  // Create a new chat session thread
  const handleCreateNewThread = async (merchantId = 'ecommerce') => {
    if (!currentUser) return;
    const newThreadId =
      typeof crypto !== 'undefined' && crypto.randomUUID
        ? crypto.randomUUID()
        : `thread_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
    try {
      const res = await fetch('/api/chat/threads', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          userId: currentUser.id,
          threadId: newThreadId,
          businessId: merchantId,
        }),
      });
      const data = await res.json();
      if (data.success) {
        const newThreadItem: ChatThread = {
          id: newThreadId,
          userId: currentUser.id,
          businessId: merchantId,
          status: 'active',
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
        };
        setThreads((prev) => [newThreadItem, ...prev]);
        setActiveThreadId(newThreadId);
        if (onThreadCreated) {
          onThreadCreated();
        }
      }
    } catch (err) {
      console.error('[Create Thread Error]:', err);
    }
  };

  // 切换商户大脑并自动定位/创建对应的会话线程，彻底消除 UX 交互门槛与多租户隔离盲区！
  const handleMerchantSwitch = async (merchantId: string) => {
    setSelectedNewThreadMerchant(merchantId);
    if (isSubmitting) return;

    // 1. 在当前已加载的历史会话中，查找是否已存在属于该商户的会话线程
    const existingThread = threads.find((t) => t.businessId === merchantId);

    if (existingThread) {
      console.log(`[Merchant Switch] 🎯 自动切换至已有的 ${merchantId} 会话: ${existingThread.id}`);
      setActiveThreadId(existingThread.id);
    } else {
      console.log(`[Merchant Switch] 🚀 未找到已有的 ${merchantId} 会话，自动为您开辟全新会话通道...`);
      await handleCreateNewThread(merchantId);
    }
  };

  // Delete a chat session thread cascade style!
  const handleDeleteThread = async (e: React.MouseEvent, threadIdToDelete: string) => {
    e.stopPropagation(); // Prevent choosing this thread upon deleting
    if (isSubmitting) return;

    const confirmDelete = window.confirm(
      '⚠️ 您确定要彻底删除该会话吗？\n该操作将物理抹除该会话下的所有聊天消息、审核单据、日志度量等关联记录，不可撤销！',
    );
    if (!confirmDelete) return;

    try {
      const res = await fetch(`/api/chat/threads?threadId=${threadIdToDelete}`, {
        method: 'DELETE',
      });
      const data = await res.json();
      if (data.success) {
        setThreads((prev) => prev.filter((t) => t.id !== threadIdToDelete));

        // If active thread got deleted, fall back to another one
        if (activeThreadId === threadIdToDelete) {
          const remainingThreads = threads.filter((t) => t.id !== threadIdToDelete);
          if (remainingThreads.length > 0) {
            setActiveThreadId(remainingThreads[0].id);
          } else {
            setActiveThreadId('');
          }
        }
      } else {
        alert(`删除失败: ${data.error || '未知数据库错误'}`);
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      console.error('[Delete Thread Client Error]:', err);
      alert(`删除出错: ${errMsg || '网络连接故障'}`);
    }
  };

  // Fetch threads on initial load when currentUser becomes available
  useEffect(() => {
    if (currentUser) {
      fetchThreads();
    }
  }, [currentUser, fetchThreads]);

  return {
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
  };
}
