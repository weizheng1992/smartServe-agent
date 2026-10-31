// 消息铃铛(mall-notifications 05):顶栏入口 + 未读徽标 + 实时信号流。
// U2 律:仅 CUST-* 渲染,游客零接入(无铃铛、无连接)。
// 未读数三源:挂载拉取 / visibilitychange 回前台重拉 / SSE 信号重拉
// (数据真源恒为 unread-count 端点,帧只当信号);标已读路径经
// notify_updated 窗口事件同频消减(cart_updated 同款先例)。
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { useLocation } from 'react-router';
import { useCurrentUser } from '../../context/UserContext';
import { notifications } from '../../lib/api';
import { MERCHANT_ID } from '../../lib/tenant';
import { openNotifyStream } from './notifyStreamConnection';

export function NotifyBell() {
  const { user } = useCurrentUser();
  const { pathname } = useLocation();
  const isCustomer = user.id.startsWith('CUST-');
  const [unread, setUnread] = useState(0);

  const refresh = useCallback(async () => {
    if (!user.id.startsWith('CUST-')) return;
    try {
      const data = (await notifications.unreadCount(user.id, MERCHANT_ID)) as {
        success?: boolean;
        data?: { unread?: number };
      };
      if (data?.success && data.data) {
        setUnread(Number(data.data.unread) || 0);
      }
    } catch {
      // 网络断:徽标保持旧值(实时增强非关键路径,页面拉取兜底),不弹错
    }
  }, [user.id]);

  useEffect(() => {
    if (!isCustomer) return undefined;
    void refresh();
    const onVisible = () => {
      if (document.visibilityState === 'visible') void refresh();
    };
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('notify_updated', onVisible);
    const handle = openNotifyStream({
      userId: user.id,
      businessId: MERCHANT_ID,
      onSignal: () => void refresh(),
    });
    return () => {
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('notify_updated', onVisible);
      handle.close();
    };
  }, [isCustomer, refresh, user.id]);

  // U2 游客律:游客零接入 —— 无铃铛、无入口、SSE 不连接(guest-* 直接不进 effect)
  if (!isCustomer) return null;

  const isActive = pathname.startsWith('/messages');
  return (
    <Link
      to="/messages"
      className={`px-3 py-1.5 text-xs font-medium rounded-lg transition shadow-2xs flex items-center space-x-1.5 ${
        isActive
          ? 'bg-emerald-600 text-white font-semibold shadow-xs'
          : 'text-slate-700 bg-white border border-slate-300 hover:bg-slate-50'
      }`}
    >
      <span>🔔 消息</span>
      {unread > 0 && (
        <span
          className={`text-[11px] px-1.5 py-0.2 rounded-full font-bold ${
            isActive ? 'bg-white text-emerald-700' : 'bg-emerald-600 text-white'
          }`}
        >
          {unread > 99 ? '99+' : unread}
        </span>
      )}
    </Link>
  );
}
