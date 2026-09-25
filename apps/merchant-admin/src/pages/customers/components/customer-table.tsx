import { type Customer, api } from '@/lib/api';
import { setSelectionKind } from '@/lib/page-context';
import { useState } from 'react';
import { Button } from 'ui';

export type { Customer };

const LEVELS = ['VIP', '金卡', '银卡'];

interface Props {
  customers: Customer[];
  onMsg: (m: string) => void;
  onChanged: () => void;
  onDetail: (c: Customer) => void;
}

/** 客户列表:勾选→PageContext(customer 类,对话实时联动);会员级改即存;
 *  详情抽屉(地址/关联券/关联订单);删除受服务端护栏。 */
export function CustomerTable({ customers, onMsg, onChanged, onDetail }: Props) {
  const [selected, setSelected] = useState<string[]>([]);

  function toggle(cid: string) {
    const next = selected.includes(cid) ? selected.filter((x) => x !== cid) : [...selected, cid];
    setSelected(next);
    const names = Object.fromEntries(
      customers.filter((c) => next.includes(c.customer_id)).map((c) => [c.customer_id, c.name]),
    );
    setSelectionKind('customer', next, names);
  }

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
        客户列表{' '}
        <span className="text-[11px] text-zinc-400">
          商户库真实客户 · 按累计消费排序 · 会员级改即存 · 有订单客户不可删
        </span>
      </div>
      {selected.length > 0 && (
        <div className="border-b border-amber-100 bg-amber-50 px-4 py-2 text-xs text-amber-700">
          已勾选 {selected.length} 位客户 —— 打开右下角助手即可带着勾选提问(如「他们最近下单是什么时候」)
        </div>
      )}
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-zinc-100 text-left text-zinc-400">
            <th className="w-10 px-3 py-2" />
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
            <tr>
              <td colSpan={7} className="px-4 py-6 text-center text-xs text-zinc-400">
                暂无客户(诚实空)
              </td>
            </tr>
          )}
          {customers.map((c) => (
            <tr key={c.customer_id} className="border-b border-zinc-50">
              <td className="px-3 py-2">
                <input
                  type="checkbox"
                  aria-label={`选择客户 ${c.name}`}
                  checked={selected.includes(c.customer_id)}
                  onChange={() => toggle(c.customer_id)}
                />
              </td>
              <td className="px-4 py-2">
                {c.name}
                <span className="ml-2 text-[11px] text-zinc-400">{c.customer_id}</span>
              </td>
              <td className="px-4 py-2">{c.phone}</td>
              <td className="px-4 py-2">¥{c.total_spent.toLocaleString()}</td>
              <td className="px-4 py-2">{c.order_count}</td>
              <td className="px-4 py-2">
                <select
                  className="rounded-lg border border-zinc-300 px-2 py-1 text-xs"
                  defaultValue={c.member_level}
                  onChange={(e) => void setLevel(c.customer_id, e.target.value)}
                >
                  {LEVELS.map((lv) => (
                    <option key={lv} value={lv}>
                      {lv}
                    </option>
                  ))}
                </select>
              </td>
              <td className="px-4 py-2">
                <Button size="sm" variant="ghost" onClick={() => onDetail(c)}>
                  详情
                </Button>
                <Button size="sm" variant="ghost" className="text-rose-600" onClick={() => void remove(c.customer_id)}>
                  删除
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
