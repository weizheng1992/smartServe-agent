import { type MerchantNotification, api } from '@/lib/api';
import { useListPage } from '@/lib/use-list-page';
import { useEffect, useRef, useState } from 'react';
import { Button } from 'ui';
import { NotifyComposeDialog } from './components/notify-compose-dialog';
import { NotifyHistoryTable } from './components/notify-history-table';

const PAGE_SIZE = 20;

/** 消息推送页(mall-notifications 04,薄编排):撰写弹窗(候选④条件挂载)+
 * 已发历史分页表。分页页码走 ref(useListPage 的 loader 闭包不吃受控 state
 * —— reload 读 loaderRef,点击时 render 未必发生,ref 是唯一不失真的通道),
 * gotoPage 单点改 ref + state 再 reload。顾客选项页级一次拉取共用(弹窗定向
 * 选择器),拉取失败弹窗内仅可广播(定向选择器空 —— 诚实,不假数据)。 */
export default function NotificationsPage() {
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [composeOpen, setComposeOpen] = useState(false);
  const [customers, setCustomers] = useState<Array<{ customerId: string; name: string }>>([]);
  const pageRef = useRef(1);

  const { rows, msg, setMsg, reload } = useListPage<MerchantNotification>(async () => {
    const body = await api.notifications.list(pageRef.current, PAGE_SIZE);
    setTotal(body.data?.total ?? 0);
    return body.data?.notifications ?? [];
  });

  useEffect(() => {
    void api.customers
      .list()
      .then((b) => setCustomers((b.customers || []).map((c) => ({ customerId: c.customer_id, name: c.name }))))
      .catch(() => setCustomers([])); // 选项拉取失败不拦页面;定向选择器空即可
  }, []);

  function gotoPage(p: number) {
    pageRef.current = p;
    setPage(p);
    void reload();
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">消息推送</div>
          <div className="mt-0.5 text-xs text-zinc-400">
            向顾客发送站内公告 / 定向消息;顾客在商城消息中心查看,广播每员工每日限 20 条
          </div>
        </div>
        <Button size="sm" onClick={() => setComposeOpen(true)}>
          + 发送消息
        </Button>
      </div>
      {msg && <div className="rounded-lg border border-zinc-200 bg-white px-4 py-2 text-xs text-zinc-600">{msg}</div>}
      <NotifyHistoryTable rows={rows} />
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 text-xs text-zinc-500">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => gotoPage(page - 1)}>
            上一页
          </Button>
          <span>
            {page} / {totalPages}
          </span>
          <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => gotoPage(page + 1)}>
            下一页
          </Button>
        </div>
      )}
      {composeOpen && (
        <NotifyComposeDialog
          customers={customers}
          onClose={() => setComposeOpen(false)}
          onMsg={(m) => {
            setMsg(m);
            void reload();
          }}
        />
      )}
    </div>
  );
}
