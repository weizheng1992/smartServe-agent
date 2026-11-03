// 消息中心页(mall-notifications 05,/messages):我的站内消息分页列表。
// 数据纪律:进页拉取兜底 + 操作后重拉(实时性由铃铛 SSE 负责,页面自身
// 拉取式 —— F5 的正确性锚);游客直达 = 无害空态(U2 律,接口本就诚实空)。
// 缺值诚实:时间/正文缺值走「—」,不编造(merchant.md 数据诚实律)。
import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';
import { StorefrontHeader } from '../components/navbar/StorefrontHeader';
import { useCurrentUser } from '../context/UserContext';
import { errMsgOf, notifications } from '../lib/api';
import { fmtDate } from '../lib/format';
import { MERCHANT_ID } from '../lib/tenant';

interface NotifyItem {
  id: string;
  title: string;
  body: string;
  msgType: string;
  isRead: boolean;
  createdAt: string;
}

const PAGE_SIZE = 20;

export default function MessagesPage() {
  const { user } = useCurrentUser();
  const [items, setItems] = useState<NotifyItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);

  const fetchPage = useCallback(
    async (targetPage: number) => {
      setLoading(true);
      setError(null);
      try {
        const data = (await notifications.list(user.id, MERCHANT_ID, targetPage)) as {
          success?: boolean;
          data?: { notifications?: NotifyItem[]; total?: number };
          message?: string;
        };
        if (data?.success && data.data) {
          setItems(data.data.notifications || []);
          setTotal(data.data.total || 0);
          setPage(targetPage);
        } else {
          setError(errMsgOf(data, '消息加载失败,请稍后重试'));
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : '消息加载失败,请稍后重试');
      } finally {
        setLoading(false);
      }
    },
    [user.id],
  );

  useEffect(() => {
    void fetchPage(1);
  }, [fetchPage]);

  const markRead = async (payload: { ids?: string[]; all?: boolean }) => {
    setActionErr(null);
    try {
      const data = (await notifications.markRead({ userId: user.id, businessId: MERCHANT_ID, ...payload })) as {
        success?: boolean;
        message?: string;
      };
      if (!data?.success) {
        setActionErr(errMsgOf(data, '标记已读失败'));
        return;
      }
      await fetchPage(page);
      window.dispatchEvent(new Event('notify_updated'));
    } catch (err) {
      setActionErr(err instanceof Error ? err.message : '标记已读失败,请稍后重试');
    }
  };

  const openItem = (item: NotifyItem) => {
    setExpandedId(expandedId === item.id ? null : item.id);
    if (!item.isRead) void markRead({ ids: [item.id] });
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const unreadInPage = items.filter((n) => !n.isRead).length;

  return (
    <div className="min-h-screen bg-slate-50">
      <StorefrontHeader />
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-xl font-bold text-slate-900">🔔 消息中心</h1>
            <p className="text-xs text-slate-500 mt-0.5">
              商户公告与定向消息 · 共 {total} 条{unreadInPage > 0 ? ` · 本页未读 ${unreadInPage} 条` : ''}
            </p>
          </div>
          {/* 入口随 total 而非本页未读:未读只在后续页时一键全部已读仍须可达(F4) */}
          {total > 0 && (
            <Button variant="outline" size="sm" onClick={() => void markRead({ all: true })}>
              全部标为已读
            </Button>
          )}
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3 mb-4">{error}</div>
        )}
        {actionErr && (
          <div className="bg-amber-50 border border-amber-200 text-amber-700 text-xs rounded-xl px-4 py-2.5 mb-4">
            {actionErr}
          </div>
        )}

        {loading ? (
          <div className="text-center text-sm text-slate-400 py-16">加载中…</div>
        ) : items.length === 0 ? (
          <div className="text-center py-16">
            <div className="text-4xl mb-3">📭</div>
            <div className="text-sm text-slate-500">暂无消息</div>
            <div className="text-xs text-slate-400 mt-1">商户发布的新公告会出现在这里</div>
          </div>
        ) : (
          <div className="space-y-2.5">
            {items.map((item) => {
              const expanded = expandedId === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => openItem(item)}
                  className={`w-full text-left bg-white border rounded-2xl px-4 py-3.5 transition cursor-pointer hover:border-emerald-300 ${
                    item.isRead ? 'border-slate-200' : 'border-emerald-300 shadow-xs'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center space-x-2 min-w-0">
                      {!item.isRead && (
                        <span
                          data-testid="notify-unread-dot"
                          className="w-2 h-2 rounded-full bg-emerald-500 shrink-0"
                        />
                      )}
                      <span
                        className={`text-sm truncate ${item.isRead ? 'text-slate-600' : 'text-slate-900 font-semibold'}`}
                      >
                        {item.title}
                      </span>
                    </div>
                    <span className="text-[11px] text-slate-400 shrink-0">{fmtDate(item.createdAt) || '—'}</span>
                  </div>
                  {expanded && (
                    <div className="mt-2.5 pt-2.5 border-t border-slate-100 text-sm text-slate-600 whitespace-pre-wrap">
                      {item.body || '—'}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        )}

        {totalPages > 1 && !loading && (
          <div className="flex items-center justify-center space-x-3 mt-6">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => void fetchPage(page - 1)}>
              上一页
            </Button>
            <span className="text-xs text-slate-500">
              {page} / {totalPages}
            </span>
            <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => void fetchPage(page + 1)}>
              下一页
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
