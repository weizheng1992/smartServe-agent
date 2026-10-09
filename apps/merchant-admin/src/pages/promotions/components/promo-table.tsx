import {
  DenseTable,
  DenseTableBody,
  DenseTableCell,
  DenseTableHead,
  DenseTableHeader,
  DenseTableRow,
} from '@/components/dense-table';
import { type Promotion, api } from '@/lib/api';
import { Fragment, useState } from 'react';
import { Button } from 'ui';
import { GrantPanel } from './grant-panel';
import { RedeemPanel } from './redeem-panel';
import { scopeLabel } from './scope';

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

/** 生效态四态(服务端派生 effectiveStatus,前端不自行算)。 */
const EFFECT_LABEL: Record<Promotion['effectiveStatus'], { text: string; cls: string }> = {
  running: { text: '进行中', cls: 'text-emerald-600' },
  scheduled: { text: '未开始', cls: 'text-zinc-500' },
  ended: { text: '已结束', cls: 'text-zinc-400' },
  disabled: { text: '已停用', cls: 'text-zinc-400' },
};

/** 服务端 isoformat(naive,无时区)→ "YYYY-MM-DD HH:mm"。 */
function shortTs(iso: string | null): string {
  return iso ? iso.slice(0, 16).replace('T', ' ') : '';
}

function windowLabel(p: Promotion): string {
  const start = shortTs(p.startAt);
  const end = shortTs(p.endAt);
  if (!start && !end) return '长期';
  return `${start || '?'} ~ ${end || '长期'}`;
}

interface Props {
  promotions: Promotion[];
  /** spu_code → 商品标题(范围回显;由页面拉取一次共享) */
  spuTitles: Record<string, string>;
  onMsg: (m: string) => void;
  onChanged: () => void;
  /** 编辑走页级 PromoFormDialog 弹窗(本表只上报,不持有表单态) */
  onEdit: (p: Promotion) => void;
}

/** 活动列表:有效期/生效态四态/券发放量、编辑(上报页级弹窗)、启停、删除、
 * 核销与发券(仅进行中,与服务端窗口闸同口径)。 */
export function PromoTable({ promotions, spuTitles, onMsg, onChanged, onEdit }: Props) {
  const [redeem, setRedeem] = useState<{ promoId: string; promoName: string } | null>(null);
  const [granting, setGranting] = useState<Promotion | null>(null);

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
          onDone={(m) => {
            onMsg(m);
            onChanged();
          }}
        />
      )}
      {granting && (
        <GrantPanel
          promo={granting}
          onCancel={() => {
            setGranting(null);
            onChanged();
          }}
          onDone={onMsg}
        />
      )}

      <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
        <DenseTable>
          <DenseTableHeader>
            <DenseTableRow className="border-b border-zinc-100 hover:bg-transparent">
              <DenseTableHead>活动</DenseTableHead>
              <DenseTableHead>类型</DenseTableHead>
              <DenseTableHead>优惠</DenseTableHead>
              <DenseTableHead>适用范围</DenseTableHead>
              <DenseTableHead>有效期</DenseTableHead>
              <DenseTableHead>状态</DenseTableHead>
              <DenseTableHead>操作</DenseTableHead>
            </DenseTableRow>
          </DenseTableHeader>
          <DenseTableBody>
            {promotions.length === 0 && (
              <DenseTableRow>
                <DenseTableCell colSpan={7} className="py-6 text-center text-xs text-zinc-400">
                  暂无活动(诚实空)
                </DenseTableCell>
              </DenseTableRow>
            )}
            {promotions.map((p) => {
              const effect = EFFECT_LABEL[p.effectiveStatus] || { text: p.status, cls: 'text-zinc-400' };
              return (
                <Fragment key={p.id}>
                  <DenseTableRow>
                    <DenseTableCell>
                      <div>{p.name}</div>
                      {(p.redemptionCount > 0 || p.discountTotal > 0) && (
                        <div className="mt-0.5 text-[11px] text-zinc-400">
                          核销 {p.redemptionCount} 单 · 让利 ¥{p.discountTotal}
                        </div>
                      )}
                    </DenseTableCell>
                    <DenseTableCell>{TYPE_LABEL[p.promoType] || p.promoType}</DenseTableCell>
                    <DenseTableCell>
                      {promoValueLabel(p)}
                      {p.promoType === 'coupon' && (
                        <div className="mt-0.5 text-[11px] text-zinc-400">
                          已领 {p.claimedCount}
                          {p.totalQuota != null ? `/上限 ${p.totalQuota}` : ''}
                        </div>
                      )}
                    </DenseTableCell>
                    <DenseTableCell className="text-zinc-500">
                      {scopeLabel(p.scopeType, p.scopeValue, spuTitles)}
                    </DenseTableCell>
                    <DenseTableCell className="text-zinc-500">{windowLabel(p)}</DenseTableCell>
                    <DenseTableCell className={effect.cls}>{effect.text}</DenseTableCell>
                    <DenseTableCell>
                      <div className="flex gap-1">
                        <Button size="sm" variant="ghost" onClick={() => onEdit(p)}>
                          编辑
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => void toggle(p)}>
                          {p.status === 'active' ? '停用' : '启用'}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => void removePromo(p)}>
                          删除
                        </Button>
                        {p.effectiveStatus === 'running' && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setRedeem({ promoId: p.id, promoName: p.name })}
                          >
                            核销
                          </Button>
                        )}
                        {p.effectiveStatus === 'running' && p.promoType === 'coupon' && (
                          <Button size="sm" variant="ghost" onClick={() => setGranting(p)}>
                            发券
                          </Button>
                        )}
                      </div>
                    </DenseTableCell>
                  </DenseTableRow>
                </Fragment>
              );
            })}
          </DenseTableBody>
        </DenseTable>
      </div>
    </>
  );
}
