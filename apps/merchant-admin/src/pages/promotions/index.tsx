import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';

interface Promotion {
  id: string;
  name: string;
  promoType: string;
  threshold: number | null;
  value: number;
  scopeType: string;
  scopeValue: string | null;
  status: string;
}
interface Effect {
  activePromotions: number;
  redemptions: number;
  totalDiscount: number;
}

const TYPE_LABEL: Record<string, string> = {
  full_reduction: '满减',
  discount: '折扣',
  coupon: '券',
};

export default function PromotionsPage() {
  const [promotions, setPromotions] = useState<Promotion[]>([]);
  const [effect, setEffect] = useState<Effect | null>(null);
  const [msg, setMsg] = useState('');
  const [form, setForm] = useState({ name: '', promoType: 'full_reduction', threshold: '', value: '' });
  const [redeem, setRedeem] = useState<{ promoId: string; promoName: string; orderId: string } | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);

  const headers = () => ({
    'Content-Type': 'application/json',
    'x-tenant-id': 'aurora',
    'x-user-id': localStorage.getItem('merchant-admin.staff') || 'boss@aurora',
  });

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/analytics/promotions', { headers: headers() });
      const body = await res.json();
      setPromotions(body.promotions || []);
      setEffect(body.effect || null);
    } catch (err) {
      setMsg(String(err));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function create() {
    setMsg('创建中…');
    const res = await fetch('/api/admin/analytics/promotions', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({
        name: form.name,
        promoType: form.promoType,
        threshold: form.threshold ? Number(form.threshold) : undefined,
        value: Number(form.value),
      }),
    });
    const body = await res.json();
    setMsg(body.success ? `✓ 已创建「${body.name}」` : `失败:${body.message}`);
    if (body.success) { setForm({ name: '', promoType: 'full_reduction', threshold: '', value: '' }); void load(); }
  }

  async function submitRedeem() {
    if (!redeem) return;
    const res = await fetch(`/api/admin/analytics/promotions/${redeem.promoId}/redeem`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-tenant-id': 'aurora', 'x-user-id': localStorage.getItem('merchant-admin.staff') || 'boss@aurora' },
      body: JSON.stringify({ orderId: redeem.orderId }),
    });
    const body = await res.json();
    setMsg(body.success ? `✓ 已核销:订单 ${body.orderId} 优惠 ¥${body.discount}` : `失败:${body.message}`);
    setRedeem(null);
    void load();
  }

  async function saveEdit(p: Promotion) {
    const res = await fetch(`/api/admin/analytics/promotions/${p.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'x-tenant-id': 'aurora', 'x-user-id': localStorage.getItem('merchant-admin.staff') || 'boss@aurora' },
      body: JSON.stringify({ name: p.name, value: p.value }),
    });
    const b = await res.json();
    setMsg(b.success ? '✓ 已保存' : `失败:${b.message}`);
    if (b.success) void load();
  }

  async function removePromo(p: Promotion) {
    const res = await fetch(`/api/admin/analytics/promotions/${p.id}`, { method: 'DELETE', headers: { 'x-tenant-id': 'aurora', 'x-user-id': localStorage.getItem('merchant-admin.staff') || 'boss@aurora' } });
    const b = await res.json();
    setMsg(b.success ? '✓ 已删除' : `失败:${b.message}`);
    void load();
  }

  async function toggle(p: Promotion) {
    await fetch(`/api/admin/analytics/promotions/${p.id}/status`, {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({ status: p.status === 'active' ? 'disabled' : 'active' }),
    });
    void load();
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-xl border border-zinc-200 bg-white p-4 text-center">
          <div className="text-xl font-semibold">{effect?.activePromotions ?? '—'}</div>
          <div className="text-[11px] text-zinc-400">进行中活动</div>
        </div>
        <div className="rounded-xl border border-zinc-200 bg-white p-4 text-center">
          <div className="text-xl font-semibold">{effect?.redemptions ?? '—'}</div>
          <div className="text-[11px] text-zinc-400">累计核销单数</div>
        </div>
        <div className="rounded-xl border border-zinc-200 bg-white p-4 text-center">
          <div className="text-xl font-semibold">¥{(effect?.totalDiscount ?? 0).toLocaleString()}</div>
          <div className="text-[11px] text-zinc-400">累计优惠金额</div>
        </div>
      </div>

      <div className="rounded-xl border border-zinc-200 bg-white p-4">
        <div className="text-sm font-medium">新建活动</div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <input className="w-40 rounded-lg border border-zinc-300 px-3 py-2" placeholder="活动名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <select className="rounded-lg border border-zinc-300 px-3 py-2" value={form.promoType} onChange={(e) => setForm({ ...form, promoType: e.target.value })}>
            <option value="full_reduction">满减</option>
            <option value="discount">折扣</option>
            <option value="coupon">券</option>
          </select>
          {form.promoType === 'full_reduction' && (
            <input className="w-28 rounded-lg border border-zinc-300 px-3 py-2" placeholder="门槛 ¥" value={form.threshold} onChange={(e) => setForm({ ...form, threshold: e.target.value })} />
          )}
          <input className="w-28 rounded-lg border border-zinc-300 px-3 py-2" placeholder={form.promoType === 'discount' ? '折扣(85=8.5折)' : '优惠 ¥'} value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
          <Button size="sm" disabled={!form.name || !form.value} onClick={() => void create()}>创建</Button>
          {msg && <span className="text-[11px] text-zinc-400">{msg}</span>}
        </div>
        <div className="mt-2 text-[11px] text-zinc-400">
          注:下单结算自动应用优惠属资金口径改动(20-D3),经独立评审后接入;当前为活动管理与效果速览。
        </div>
      </div>

      {redeem && (
        <div className="rounded-xl border border-blue-200 bg-blue-50/60 p-4">
          <div className="text-sm font-medium">核销「{redeem.promoName}」</div>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
            <input className="w-64 rounded-lg border border-zinc-300 px-3 py-2" placeholder="订单号,如 AURORA-ORD-2026-9091" value={redeem.orderId} onChange={(e) => setRedeem({ ...redeem, orderId: e.target.value })} />
            <Button size="sm" disabled={!redeem.orderId} onClick={() => void submitRedeem()}>确认核销</Button>
            <Button size="sm" variant="ghost" onClick={() => setRedeem(null)}>取消</Button>
            <span className="text-[11px] text-zinc-400">优惠额由服务端按活动规则×订单实付计算;同订单×同活动幂等</span>
          </div>
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-zinc-100 text-left text-zinc-400">
              <th className="px-4 py-2 font-medium">活动</th>
              <th className="px-4 py-2 font-medium">类型</th>
              <th className="px-4 py-2 font-medium">优惠</th>
              <th className="px-4 py-2 font-medium">状态</th>
              <th className="px-4 py-2 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {promotions.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-6 text-center text-xs text-zinc-400">暂无活动(诚实空)</td></tr>
            )}
            {promotions.map((p) => (
              <tr key={p.id} className="border-b border-zinc-50">
                <td className="px-4 py-2">
                  {editingId === p.id ? (
                    <input className="w-32 rounded border border-zinc-300 px-2 py-1" defaultValue={p.name}
                      onBlur={(e) => { p.name = e.target.value; void saveEdit(p); setEditingId(null); }} />
                  ) : (
                    p.name
                  )}
                </td>
                <td className="px-4 py-2">{TYPE_LABEL[p.promoType] || p.promoType}</td>
                <td className="px-4 py-2">
                  {p.promoType === 'full_reduction' ? `满 ¥${p.threshold} 减 ¥${p.value}` : p.promoType === 'discount' ? `${p.value / 10} 折` : `¥${p.value} 券`}
                </td>
                <td className="px-4 py-2">
                  <span className={p.status === 'active' ? 'text-emerald-600' : 'text-zinc-400'}>{p.status === 'active' ? '进行中' : '已停用'}</span>
                </td>
                <td className="px-4 py-2">
                  <div className="flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => setEditingId(editingId === p.id ? null : p.id)}>
                      {editingId === p.id ? '取消' : '编辑'}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => void toggle(p)}>{p.status === 'active' ? '停用' : '启用'}</Button>
                    <Button size="sm" variant="ghost" onClick={() => void removePromo(p)}>删除</Button>
                    {p.status === 'active' && (
                      <Button size="sm" variant="ghost" onClick={() => setRedeem({ promoId: p.id, promoName: p.name, orderId: '' })}>核销</Button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
