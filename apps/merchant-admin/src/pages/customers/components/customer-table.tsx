import {
  DenseTable,
  DenseTableBody,
  DenseTableCell,
  DenseTableHead,
  DenseTableHeader,
  DenseTableRow,
} from '@/components/dense-table';
import { type Customer, api } from '@/lib/api';
import { setSelectionKind } from '@/lib/page-context';
import { useState } from 'react';
import { Button, Checkbox, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from 'ui';

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
      <DenseTable>
        <DenseTableHeader>
          <DenseTableRow className="border-b border-zinc-100 hover:bg-transparent">
            <DenseTableHead className="w-10 px-3" />
            <DenseTableHead>客户</DenseTableHead>
            <DenseTableHead>电话</DenseTableHead>
            <DenseTableHead>累计消费</DenseTableHead>
            <DenseTableHead>订单数</DenseTableHead>
            <DenseTableHead>会员级(改即存)</DenseTableHead>
            <DenseTableHead>操作</DenseTableHead>
          </DenseTableRow>
        </DenseTableHeader>
        <DenseTableBody>
          {customers.length === 0 && (
            <DenseTableRow>
              <DenseTableCell colSpan={7} className="py-6 text-center text-xs text-zinc-400">
                暂无客户(诚实空)
              </DenseTableCell>
            </DenseTableRow>
          )}
          {customers.map((c) => (
            <DenseTableRow key={c.customer_id}>
              <DenseTableCell className="px-3">
                <Checkbox
                  aria-label={`选择客户 ${c.name}`}
                  checked={selected.includes(c.customer_id)}
                  onCheckedChange={() => toggle(c.customer_id)}
                />
              </DenseTableCell>
              <DenseTableCell>
                {c.name}
                <span className="ml-2 text-[11px] text-zinc-400">{c.customer_id}</span>
              </DenseTableCell>
              <DenseTableCell>{c.phone}</DenseTableCell>
              <DenseTableCell>¥{c.total_spent.toLocaleString()}</DenseTableCell>
              <DenseTableCell>{c.order_count}</DenseTableCell>
              <DenseTableCell>
                <Select defaultValue={c.member_level} onValueChange={(v) => void setLevel(c.customer_id, v)}>
                  <SelectTrigger
                    aria-label={`会员级:${c.name}`}
                    className="h-auto w-24 rounded-lg border-zinc-300 px-2 py-1 text-xs"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {LEVELS.map((lv) => (
                      <SelectItem key={lv} value={lv}>
                        {lv}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </DenseTableCell>
              <DenseTableCell>
                <Button size="sm" variant="ghost" onClick={() => onDetail(c)}>
                  详情
                </Button>
                <Button size="sm" variant="ghost" className="text-rose-600" onClick={() => void remove(c.customer_id)}>
                  删除
                </Button>
              </DenseTableCell>
            </DenseTableRow>
          ))}
        </DenseTableBody>
      </DenseTable>
    </div>
  );
}
