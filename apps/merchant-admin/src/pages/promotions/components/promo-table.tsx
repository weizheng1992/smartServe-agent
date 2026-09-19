import { useState } from 'react';
import { Button } from 'ui';
import { api, type Promotion } from '@/lib/api';
import { RedeemPanel } from './redeem-panel';

const TYPE_LABEL: Record<string, string> = {
  full_reduction: '满减',
  discount: '折扣',
  coupon: '券',
};

function promoValueLabel(p: Promotion): string {
  if (p.promoType === 'full_reduction') return `满 ¥${p.threshold} 减 ¥${p.value}`;
  if (p.promoType === 'discount') return `${p.value / 10} 折`;
  return `¥${p.value} 券`;
}

interface Props {
  promotions: Promotion[];
  onMsg: (m: string) => void;
  onChanged: () => void;
}

/** 活动列表:行内编辑(名称失焦即存)、启停、删除(有核销记录不可删)、
 *  核销面板(挂在表头上方)。 */
export function PromoTable({ promotions, onMsg, onChanged }: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [redeem, setRedeem] = useState<{ promoId: string; promoName: string } | null>(null);

  async function saveEdit(p: Promotion, name: string) {
    const b = await api.promotions.update(p.id, { name, value: p.value });
    onMsg(b.success ? '✓ 已保存' : `失败:${b.message}`);
    if (b.success) onChanged();
  }

  async function toggle(p: Promotion) {
    const b = await api.promotions.setStatus(p.id, p.status === 'active' ? 'disabled' : 'active');
    onMsg(b.success ? `✓ 「${p.name}」已${p.status === 'active' ? '停用' : '启用'}` : `失败:${b.message}`);
    onChanged();
  }

  async function removePromo(p: Promotion) {
    const b = await api.promotions.remove(p.id);
    onMsg(b.success ? '✓ 已删除' : `失败:${b.message}`);
    onChanged();
  }

  const redeemPromo = redeem ? promotions.find((p) => p.id === redeem.promoId) : null;

  return (
    <>
      {redeemPromo && (
        <RedeemPanel
          promo={redeemPromo}
          onCancel={() => setRedeem(null)}
          onDone={(m) => { onMsg(m); onChanged(); }}
        />
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
                      onBlur={(e) => { void saveEdit(p, e.target.value); setEditingId(null); }} />
                  ) : (
                    p.name
                  )}
                </td>
                <td className="px-4 py-2">{TYPE_LABEL[p.promoType] || p.promoType}</td>
                <td className="px-4 py-2">{promoValueLabel(p)}</td>
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
                      <Button size="sm" variant="ghost" onClick={() => setRedeem({ promoId: p.id, promoName: p.name })}>核销</Button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
