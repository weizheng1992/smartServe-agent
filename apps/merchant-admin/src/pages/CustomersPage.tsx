import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';
import { currentStaff } from '@/lib/api';

interface Customer {
  customer_id: string;
  name: string;
  phone: string;
  member_level: string;
  total_spent: number;
  order_count: number;
}

const LEVELS = ['VIP', '金卡', '银卡'];

export default function CustomersPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [msg, setMsg] = useState('');
  const [newCust, setNewCust] = useState({ name: '', phone: '' });

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/analytics/customers', {
        headers: { 'x-tenant-id': 'aurora', 'x-user-id': currentStaff() },
      });
      setCustomers((await res.json()).customers || []);
    } catch (err) {
      setMsg(String(err));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function setLevel(customerId: string, memberLevel: string) {
    const res = await fetch(`/api/admin/analytics/customers/${customerId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'x-tenant-id': 'aurora', 'x-user-id': currentStaff() },
      body: JSON.stringify({ memberLevel }),
    });
    const body = await res.json();
    setMsg(body.success ? `✓ ${customerId} 会员级 → ${memberLevel}` : `失败:${body.message}`);
    if (body.success) void load();
  }

  async function createCustomer() {
    const name = newCust.name.trim(); const phone = newCust.phone.trim();
    if (!name || !phone) return;
    const res = await fetch('/api/admin/analytics/customers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-tenant-id': 'aurora', 'x-user-id': currentStaff() },
      body: JSON.stringify({ name, phone }),
    });
    const body = await res.json();
    setMsg(body.success ? `✓ 已新增客户 ${body.customerId}` : `失败:${body.message}`);
    if (body.success) { setNewCust({ name: '', phone: '' }); void load(); }
  }

  async function deleteCustomer(cid: string) {
    const res = await fetch(`/api/admin/analytics/customers/${cid}`, {
      method: 'DELETE',
      headers: { 'x-tenant-id': 'aurora', 'x-user-id': currentStaff() },
    });
    const body = await res.json();
    setMsg(body.success ? '✓ 已删除' : `失败:${body.message}`);
    if (body.success) void load();
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="rounded-xl border border-zinc-200 bg-white p-4">
        <div className="text-sm font-medium">新增客户</div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <input className="w-32 rounded-lg border border-zinc-300 px-3 py-2" placeholder="姓名" value={newCust.name} onChange={(e) => setNewCust({ ...newCust, name: e.target.value })} />
          <input className="w-40 rounded-lg border border-zinc-300 px-3 py-2" placeholder="电话" value={newCust.phone} onChange={(e) => setNewCust({ ...newCust, phone: e.target.value })} />
          <Button size="sm" disabled={!newCust.name || !newCust.phone} onClick={() => void createCustomer()}>新增</Button>
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
        <div className="border-b border-zinc-100 px-4 py-3 text-sm font-medium">
          客户列表 <span className="text-[11px] text-zinc-400">商户库真实客户 · 按累计消费排序 · 会员级改即存 · 有订单客户不可删</span>
        </div>
      {msg && <div className="px-4 py-2 text-[11px] text-zinc-500">{msg}</div>}
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-zinc-100 text-left text-zinc-400">
            <th className="px-4 py-2 font-medium">客户</th>
            <th className="px-4 py-2 font-medium">电话</th>
            <th className="px-4 py-2 font-medium">累计消费</th>
            <th className="px-4 py-2 font-medium">订单数</th>
            <th className="px-4 py-2 font-medium">会员级(改即存)</th>
            <th className="px-4 py-2 font-medium">操作</th>
          </tr>
        </thead>
        <tbody>
          {customers.length === 0 && (
            <tr><td colSpan={6} className="px-4 py-6 text-center text-xs text-zinc-400">暂无客户(诚实空)</td></tr>
          )}
          {customers.map((c) => (
            <tr key={c.customer_id} className="border-b border-zinc-50">
              <td className="px-4 py-2">{c.name}<span className="ml-2 text-[11px] text-zinc-400">{c.customer_id}</span></td>
              <td className="px-4 py-2">{c.phone}</td>
              <td className="px-4 py-2">¥{c.total_spent.toLocaleString()}</td>
              <td className="px-4 py-2">{c.order_count}</td>
              <td className="px-4 py-2">
                <select
                  className="rounded-lg border border-zinc-300 px-2 py-1 text-xs"
                  defaultValue={c.member_level}
                  onChange={(e) => void setLevel(c.customer_id, e.target.value)}
                >
                  {LEVELS.map((lv) => <option key={lv} value={lv}>{lv}</option>)}
                </select>
              </td>
              <td className="px-4 py-2">
                <Button size="sm" variant="ghost" className="text-rose-600" onClick={() => void deleteCustomer(c.customer_id)}>删除</Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}
