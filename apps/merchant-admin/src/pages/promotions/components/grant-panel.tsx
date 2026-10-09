import { type Customer, type Promotion, api } from '@/lib/api';
import { useEffect, useMemo, useState } from 'react';
import { Button, Input } from 'ui';

interface Props {
  promo: Promotion;
  onCancel: () => void;
  onDone: (msg: string) => void;
}

/** 发券面板:按姓名/手机号搜客户,逐个发放(可连续发;重复发/超上限被服务端
 * 护栏拦截并如实呈现 message);头部带剩余可发(有上限时)。 */
export function GrantPanel({ promo, onCancel, onDone }: Props) {
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
    <div className="rounded-xl border border-blue-200 bg-blue-50/60 p-4">
      <div className="text-sm font-medium">
        发券「{promo.name}」
        {remaining != null && (
          <span className="ml-2 text-[11px] text-zinc-500">
            剩余可发 {remaining}/{promo.totalQuota}
          </span>
        )}
        <span className="ml-2 text-[11px] text-zinc-400">按姓名/手机号/客户号搜索,可连续发放</span>
      </div>
      <Input
        className="mt-2 h-auto w-64 rounded-lg border-zinc-300 px-3 py-2 text-xs shadow-none focus-visible:ring-0"
        placeholder="搜索客户…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="mt-2 space-y-1">
        {hits.length === 0 && <div className="text-xs text-zinc-400">暂无匹配客户</div>}
        {hits.map((c) => (
          <div
            key={c.customer_id}
            className="flex items-center justify-between rounded-lg bg-white px-3 py-1.5 text-xs"
          >
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
      <div className="mt-2">
        <Button size="sm" variant="ghost" onClick={onCancel}>
          完成
        </Button>
      </div>
    </div>
  );
}
