import { Button } from 'ui';
import { api } from '@/lib/api';

export interface Customer {
  customer_id: string;
  name: string;
  phone: string;
  member_level: string;
  total_spent: number;
  order_count: number;
}

const LEVELS = ['VIP', '金卡', '银卡'];

interface Props {
  customers: Customer[];
  onMsg: (m: string) => void;
  onChanged: () => void;
}

/** 客户列表:会员级下拉改即存;删除受"名下有订单不可删"服务端护栏。 */
export function CustomerTable({ customers, onMsg, onChanged }: Props) {
  async function setLevel(customerId: string, memberLevel: string) {
    const body = await api.customers.update(customerId, { memberLevel });
    onMsg(body.success ? `✓ ${customerId} 会员级 → ${memberLevel}` : `失败:${body.message}`);
    if (body.success) onChanged();
  }

  async function remove(cid: string) {
    const body = await api.customers.remove(cid);
    onMsg(body.success ? '✓ 已删除' : `失败:${body.message}`);
    if (body.success) onChanged();
  }

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
      <div className="border-b border-zinc-100 px-4 py-3 text-sm font-medium">
        客户列表 <span className="text-[11px] text-zinc-400">商户库真实客户 · 按累计消费排序 · 会员级改即存 · 有订单客户不可删</span>
      </div>
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
                <Button size="sm" variant="ghost" className="text-rose-600" onClick={() => void remove(c.customer_id)}>删除</Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
