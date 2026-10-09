import { type Customer, type Promotion, api } from '@/lib/api';
import { useEffect, useMemo, useState } from 'react';
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, Input } from 'ui';

interface Props {
  promo: Promotion;
  onClose: () => void;
  /** 发放结果消息(连续发放不关窗,由页面负责刷新) */
  onDone: (msg: string) => void;
}

/** 发券弹窗:按姓名/手机号搜客户,逐个发放(可连续发;重复发/超上限被服务端
 * 护栏拦截并如实呈现 message);头部带剩余可发(有上限时)。 */
export function GrantDialog({ promo, onClose, onDone }: Props) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [query, setQuery] = useState('');
  const [granted, setGranted] = useState<Set<string>>(new Set());
  const [claimed, setClaimed] = useState<number | null>(promo.claimedCount);

  useEffect(() => {
    void api.customers.list().then((b) => setCustomers(b.customers || []));
  }, []);

  const hits = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return customers.slice(0, 8);
    return customers.filter((c) => `${c.name} ${c.phone} ${c.customer_id}`.toLowerCase().includes(q)).slice(0, 8);
  }, [customers, query]);

  async function grant(c: Customer) {
    const b = await api.promotions.grant(promo.id, c.customer_id);
    if (b.success) {
      setGranted((prev) => new Set(prev).add(c.customer_id));
      setClaimed((n) => (n == null ? n : n + 1));
      onDone(`✓ 已向 ${c.name}(${c.customer_id})发放「${promo.name}」`);
    } else {
      // 量控/查重等服务端拒发如实呈现(发放已达上限等)
      onDone(`发放失败:${b.error || b.message}`);
    }
  }

  const remaining = promo.totalQuota != null && claimed != null ? Math.max(promo.totalQuota - claimed, 0) : null;

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md rounded-xl border-zinc-200 text-zinc-900 shadow-xl">
        <DialogHeader className="pb-3 border-b border-zinc-100">
          <DialogTitle className="text-base font-bold text-zinc-900">
            发券「{promo.name}」
            {remaining != null && (
              <span className="ml-2 text-[11px] font-normal text-zinc-500">
                剩余可发 {remaining}/{promo.totalQuota}
              </span>
            )}
          </DialogTitle>
          <p className="mt-1 text-xs text-zinc-500">按姓名/手机号/客户号搜索,可连续发放</p>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto py-4 text-xs">
          <Input
            className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
            placeholder="搜索客户…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="space-y-1">
            {hits.length === 0 && <div className="text-xs text-zinc-400">暂无匹配客户</div>}
            {hits.map((c) => (
              <div key={c.customer_id} className="flex items-center justify-between rounded-lg bg-zinc-50 px-3 py-1.5">
                <span>
                  {c.name}
                  <span className="ml-2 text-zinc-400">{c.phone}</span>
                  <span className="ml-2 font-mono text-[10px] text-zinc-400">{c.customer_id}</span>
                </span>
                <Button size="sm" variant="ghost" disabled={granted.has(c.customer_id)} onClick={() => void grant(c)}>
                  {granted.has(c.customer_id) ? '✓ 已发' : '发放'}
                </Button>
              </div>
            ))}
          </div>
        </div>
        <DialogFooter className="gap-2 pt-3 sm:gap-0 border-t border-zinc-100">
          <Button type="button" variant="outline" size="sm" onClick={onClose} className="text-xs cursor-pointer">
            完成
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
