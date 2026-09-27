import { type Promotion, type Spu, api } from '@/lib/api';
import { Fragment, useEffect, useState } from 'react';
import { Button } from 'ui';
import { GrantPanel } from './grant-panel';
import { RedeemPanel } from './redeem-panel';
import { scopeEditableFor } from './scope';
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

/** ISO → datetime-local 值(YYYY-MM-DDTHH:mm)。 */
function dtLocalValue(iso: string | null): string {
  return iso ? iso.slice(0, 16) : '';
}

/** 展开行编辑表单(字符串态,提交时归一)。 */
interface EditForm {
  id: string;
  name: string;
  threshold: string;
  value: string;
  scopeType: string;
  scopeValue: string;
  startAt: string;
  endAt: string;
  totalQuota: string;
}

function editFormOf(p: Promotion): EditForm {
  return {
    id: p.id,
    name: p.name,
    threshold: p.threshold == null ? '' : String(p.threshold),
    value: String(p.value),
    scopeType: p.scopeType,
    scopeValue: p.scopeValue || '',
    startAt: dtLocalValue(p.startAt),
    endAt: dtLocalValue(p.endAt),
    totalQuota: p.totalQuota == null ? '' : String(p.totalQuota),
  };
}

interface Props {
  promotions: Promotion[];
  onMsg: (m: string) => void;
  onChanged: () => void;
}

/** 活动列表:有效期/生效态四态/券发放量、展开行一次改齐(名称/门槛/面额/
 * 时间窗/范围/上限)、启停、删除、核销与发券(仅进行中,与服务端窗口闸同口径)。 */
export function PromoTable({ promotions, onMsg, onChanged }: Props) {
  const [edit, setEdit] = useState<EditForm | null>(null);
  const [redeem, setRedeem] = useState<{ promoId: string; promoName: string } | null>(null);
  const [granting, setGranting] = useState<Promotion | null>(null);
  const [spus, setSpus] = useState<Spu[]>([]);

  useEffect(() => {
    void api.products.list().then((b) => setSpus(b.spus || []));
  }, []);
  const spuTitles = Object.fromEntries(spus.map((s) => [s.spu_code, s.title]));

  async function saveEdit(f: EditForm) {
    // PATCH 全字段:服务端区分「未传」与「传 null」—— endAt 空置长期、
    // totalQuota 空清上限、startAt 空保持原值(引擎 update_promotion 语义)。
    // 门槛仅满减携带;其余类型一律 null(不把表单残留值写进库)。
    const promoType = promotions.find((p) => p.id === f.id)?.promoType;
    const b = await api.promotions.update(f.id, {
      name: f.name,
      value: Number(f.value),
      threshold: promoType === 'full_reduction' && f.threshold ? Number(f.threshold) : null,
      scopeType: f.scopeType,
      scopeValue: f.scopeType === 'spu' ? f.scopeValue : null,
      startAt: f.startAt || undefined,
      endAt: f.endAt || null,
      totalQuota: f.totalQuota ? Number(f.totalQuota) : null,
    });
    onMsg(b.success ? '✓ 已保存' : `失败:${b.message}`);
    if (b.success) {
      setEdit(null);
      onChanged();
    }
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
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-zinc-100 text-left text-zinc-400">
              <th className="px-4 py-2 font-medium">活动</th>
              <th className="px-4 py-2 font-medium">类型</th>
              <th className="px-4 py-2 font-medium">优惠</th>
              <th className="px-4 py-2 font-medium">适用范围</th>
              <th className="px-4 py-2 font-medium">有效期</th>
              <th className="px-4 py-2 font-medium">状态</th>
              <th className="px-4 py-2 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {promotions.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-xs text-zinc-400">
                  暂无活动(诚实空)
                </td>
              </tr>
            )}
            {promotions.map((p) => {
              const effect = EFFECT_LABEL[p.effectiveStatus] || { text: p.status, cls: 'text-zinc-400' };
              const editable = scopeEditableFor(p.promoType);
              return (
                <Fragment key={p.id}>
                  <tr className="border-b border-zinc-50">
                    <td className="px-4 py-2">
                      <div>{p.name}</div>
                      {(p.redemptionCount > 0 || p.discountTotal > 0) && (
                        <div className="mt-0.5 text-[11px] text-zinc-400">
                          核销 {p.redemptionCount} 单 · 让利 ¥{p.discountTotal}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2">{TYPE_LABEL[p.promoType] || p.promoType}</td>
                    <td className="px-4 py-2">
                      {promoValueLabel(p)}
                      {p.promoType === 'coupon' && (
                        <div className="mt-0.5 text-[11px] text-zinc-400">
                          已领 {p.claimedCount}
                          {p.totalQuota != null ? `/上限 ${p.totalQuota}` : ''}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2 text-zinc-500">{scopeLabel(p.scopeType, p.scopeValue, spuTitles)}</td>
                    <td className="px-4 py-2 text-zinc-500">{windowLabel(p)}</td>
                    <td className={`px-4 py-2 ${effect.cls}`}>{effect.text}</td>
                    <td className="px-4 py-2">
                      <div className="flex gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setEdit(edit?.id === p.id ? null : editFormOf(p))}
                        >
                          {edit?.id === p.id ? '取消' : '编辑'}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => void toggle(p)}>
                          {p.status === 'active' ? '停用' : '启用'}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => void removePromo(p)}>
                          删除
                        </Button>
                        {p.effectiveStatus === 'running' && (
                          <Button size="sm" variant="ghost" onClick={() => setRedeem({ promoId: p.id, promoName: p.name })}>
                            核销
                          </Button>
                        )}
                        {p.effectiveStatus === 'running' && p.promoType === 'coupon' && (
                          <Button size="sm" variant="ghost" onClick={() => setGranting(p)}>
                            发券
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                  {edit?.id === p.id && (
                    <tr className="border-b border-zinc-50 bg-zinc-50/60">
                      <td colSpan={7} className="px-4 py-3">
                        <div className="flex flex-wrap items-center gap-2 text-xs">
                          <input
                            className="w-40 rounded-lg border border-zinc-300 px-3 py-2"
                            placeholder="活动名称"
                            value={edit.name}
                            onChange={(e) => setEdit({ ...edit, name: e.target.value })}
                          />
                          {p.promoType === 'full_reduction' && (
                            <input
                              className="w-28 rounded-lg border border-zinc-300 px-3 py-2"
                              placeholder="门槛 ¥"
                              value={edit.threshold}
                              onChange={(e) => setEdit({ ...edit, threshold: e.target.value })}
                            />
                          )}
                          <input
                            className="w-28 rounded-lg border border-zinc-300 px-3 py-2"
                            placeholder={p.promoType === 'discount' ? '折扣(85=8.5折)' : '优惠 ¥'}
                            value={edit.value}
                            onChange={(e) => setEdit({ ...edit, value: e.target.value })}
                          />
                          {editable && (
                            <>
                              <select
                                className="rounded-lg border border-zinc-300 px-3 py-2"
                                value={edit.scopeType}
                                onChange={(e) => setEdit({ ...edit, scopeType: e.target.value, scopeValue: '' })}
                              >
                                <option value="all">全部商品</option>
                                <option value="spu">指定商品</option>
                              </select>
                              {edit.scopeType === 'spu' && (
                                <select
                                  className="w-48 rounded-lg border border-zinc-300 px-3 py-2"
                                  value={edit.scopeValue}
                                  onChange={(e) => setEdit({ ...edit, scopeValue: e.target.value })}
                                >
                                  <option value="">选择商品…</option>
                                  {spus.map((s) => (
                                    <option key={s.id} value={s.spu_code}>
                                      {s.title}({s.spu_code})
                                    </option>
                                  ))}
                                </select>
                              )}
                            </>
                          )}
                          <input
                            type="datetime-local"
                            className="rounded-lg border border-zinc-300 px-3 py-2"
                            value={edit.startAt}
                            onChange={(e) => setEdit({ ...edit, startAt: e.target.value })}
                          />
                          <span className="text-zinc-400">至</span>
                          <input
                            type="datetime-local"
                            className="rounded-lg border border-zinc-300 px-3 py-2"
                            value={edit.endAt}
                            onChange={(e) => setEdit({ ...edit, endAt: e.target.value })}
                            placeholder="留空 = 长期"
                          />
                          {p.promoType === 'coupon' && (
                            <input
                              className="w-32 rounded-lg border border-zinc-300 px-3 py-2"
                              placeholder="发放上限(空=不限)"
                              value={edit.totalQuota}
                              onChange={(e) => setEdit({ ...edit, totalQuota: e.target.value })}
                            />
                          )}
                          <Button
                            size="sm"
                            disabled={!edit.name || !edit.value || (edit.scopeType === 'spu' && !edit.scopeValue)}
                            onClick={() => void saveEdit(edit)}
                          >
                            保存
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setEdit(null)}>
                            取消
                          </Button>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
