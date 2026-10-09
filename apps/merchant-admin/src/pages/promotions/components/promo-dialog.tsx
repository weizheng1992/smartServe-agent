import { type Promotion, type Spu, api } from '@/lib/api';
import { useEffect, useState } from 'react';
import {
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from 'ui';
import { scopeEditableFor } from './scope';

interface Props {
  open: boolean;
  /** null = 新建;非空 = 编辑该活动(类型创建后不可改,PATCH 不携带 promoType) */
  promo: Promotion | null;
  spus: Spu[];
  onClose: () => void;
  /** 保存成功回调(消息横幅文案);失败在弹窗内呈现,不关闭 */
  onSaved: (msg: string) => void;
}

/** datetime-local 本地当前时刻(分钟精度)。 */
function localNow(): string {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

/** 表单字符串态(提交时归一)。 */
interface FormState {
  name: string;
  promoType: string;
  threshold: string;
  value: string;
  scopeType: string;
  scopeValue: string;
  startAt: string;
  endAt: string;
  totalQuota: string;
}

function formOf(p: Promotion | null): FormState {
  if (!p) {
    return {
      name: '',
      promoType: 'full_reduction',
      threshold: '',
      value: '',
      scopeType: 'all',
      scopeValue: '',
      startAt: localNow(),
      endAt: '',
      totalQuota: '',
    };
  }
  return {
    name: p.name,
    promoType: p.promoType,
    threshold: p.threshold == null ? '' : String(p.threshold),
    value: String(p.value),
    scopeType: p.scopeType,
    scopeValue: p.scopeValue || '',
    startAt: p.startAt ? p.startAt.slice(0, 16) : '',
    endAt: p.endAt ? p.endAt.slice(0, 16) : '',
    totalQuota: p.totalQuota == null ? '' : String(p.totalQuota),
  };
}

const TYPE_META: Record<string, { title: string; desc: string }> = {
  full_reduction: { title: '满减', desc: '满 X 元减 Y 元' },
  discount: { title: '折扣', desc: '整单按折扣(85 = 8.5 折)' },
  coupon: { title: '券', desc: '客户领取后抵扣,可设发放上限' },
};

const TYPE_LABEL: Record<string, string> = {
  full_reduction: '满减',
  discount: '折扣',
  coupon: '券',
};

/** 实时规则预览(数值未填全/非法时回空,不硬凑)。 */
function rulePreview(f: FormState): string {
  const v = Number(f.value);
  if (!f.value || !Number.isFinite(v)) return '';
  if (f.promoType === 'full_reduction') {
    const t = Number(f.threshold);
    return Number.isFinite(t) && t > 0 ? `满 ¥${t} 减 ¥${v}` : `减 ¥${v}`;
  }
  if (f.promoType === 'discount') return `${v / 10} 折`;
  return `¥${v} 券`;
}

/** 轻校验(提交前;返回空串 = 通过)。 */
function validate(f: FormState): string {
  if (!f.name.trim()) return '请填写活动名称';
  const v = Number(f.value);
  if (!f.value || !Number.isFinite(v) || v <= 0) return '请填写有效的优惠数值';
  if (f.promoType === 'discount' && (v < 1 || v >= 100)) return '折扣须为 1-99(85 = 8.5 折)';
  if (f.promoType === 'full_reduction' && f.threshold) {
    const t = Number(f.threshold);
    if (!Number.isFinite(t) || t <= 0) return '门槛须为正数';
  }
  if (f.scopeType === 'spu' && !f.scopeValue) return '请选择适用商品';
  if (f.startAt && f.endAt && f.endAt < f.startAt) return '结束时间须晚于开始时间';
  if (f.promoType === 'coupon' && f.totalQuota) {
    const q = Number(f.totalQuota);
    if (!Number.isInteger(q) || q <= 0) return '发放上限须为正整数';
  }
  return '';
}

/** 新建/编辑活动弹窗(一表两态):
 * - 类型以卡片选择(仅新建可改;编辑态引擎不支持改类型,只读展示);
 * - 满减出门槛、券出发放上限、满减/折扣出适用范围(券型引擎无视范围,不展示);
 * - 时间窗缺省从现在开始、止空 = 长期;
 * - 编辑 PATCH 按「携带即更新」发全字段:endAt null 置长期、totalQuota null 清
 *   上限、startAt 空保持原值、门槛仅满减携带(引擎 update_promotion 语义)。 */
export function PromoFormDialog({ open, promo, spus, onClose, onSaved }: Props) {
  const [form, setForm] = useState<FormState>(() => formOf(promo));
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  // 打开时按目标活动重置(新建 = 空表单 + 起始当前;编辑 = 预填当前值)
  useEffect(() => {
    if (open) {
      setForm(formOf(promo));
      setErr('');
    }
  }, [open, promo]);

  const isEdit = promo != null;
  const set = (patch: Partial<FormState>) => setForm((f) => ({ ...f, ...patch }));

  async function submit() {
    const invalid = validate(form);
    if (invalid) {
      setErr(invalid);
      return;
    }
    setBusy(true);
    try {
      if (promo) {
        // PATCH 全字段:服务端区分「未传」与「传 null」—— endAt 空置长期、
        // totalQuota 空清上限、startAt 空保持原值;门槛仅满减携带。
        const b = await api.promotions.update(promo.id, {
          name: form.name,
          value: Number(form.value),
          threshold: form.promoType === 'full_reduction' && form.threshold ? Number(form.threshold) : null,
          scopeType: form.scopeType,
          scopeValue: form.scopeType === 'spu' ? form.scopeValue : null,
          startAt: form.startAt || undefined,
          endAt: form.endAt || null,
          totalQuota: form.totalQuota ? Number(form.totalQuota) : null,
        });
        if (b.success) {
          onSaved(`✓ 已保存「${form.name}」`);
          onClose();
        } else {
          setErr(`失败:${b.message}`);
        }
      } else {
        const b = await api.promotions.create({
          name: form.name,
          promoType: form.promoType,
          threshold: form.promoType === 'full_reduction' && form.threshold ? Number(form.threshold) : undefined,
          value: Number(form.value),
          scopeType: form.scopeType,
          scopeValue: form.scopeType === 'spu' ? form.scopeValue : undefined,
          startAt: form.startAt || undefined,
          endAt: form.endAt || undefined,
          totalQuota: form.promoType === 'coupon' && form.totalQuota ? Number(form.totalQuota) : undefined,
        });
        if (b.success) {
          onSaved(`✓ 已创建「${b.name}」`);
          onClose();
        } else {
          setErr(`失败:${b.message}`);
        }
      }
    } finally {
      setBusy(false);
    }
  }

  const preview = rulePreview(form);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-xl p-6 bg-white text-slate-900 border-slate-200">
        <DialogHeader className="pb-3 border-b border-slate-100">
          <DialogTitle className="text-base font-bold text-slate-900">
            {isEdit ? `编辑活动 · ${promo?.name}` : '新建活动'}
          </DialogTitle>
          <p className="mt-1 text-xs text-slate-500">
            {isEdit
              ? `${TYPE_LABEL[form.promoType] || form.promoType} · 类型创建后不可改,其余字段可一次改齐`
              : '结算时按规则自动应用;时间窗外的活动不参与结算'}
          </p>
        </DialogHeader>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto py-4 text-xs">
          {/* 活动类型:卡片三选(仅新建);编辑态只读徽标 */}
          {isEdit ? (
            <div className="flex items-center gap-2">
              <span className="text-zinc-500">类型</span>
              <span className="rounded bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-600">
                {TYPE_LABEL[form.promoType] || form.promoType}(不可改)
              </span>
            </div>
          ) : (
            <div>
              <div className="mb-1.5 font-medium text-zinc-700">活动类型</div>
              <div className="grid grid-cols-3 gap-2">
                {Object.entries(TYPE_META).map(([value, meta]) => (
                  <Button
                    key={value}
                    type="button"
                    variant="outline"
                    onClick={() => set({ promoType: value, totalQuota: '' })}
                    className={`h-auto cursor-pointer rounded-lg px-3 py-2 text-left font-normal shadow-none ${
                      form.promoType === value
                        ? 'border-zinc-900 bg-zinc-50 ring-1 ring-zinc-900 hover:bg-zinc-50'
                        : 'border-zinc-200 hover:border-zinc-400'
                    }`}
                  >
                    <span className="block w-full">
                      <span className="block text-xs font-medium text-zinc-800">{meta.title}</span>
                      <span className="mt-0.5 block text-[10px] font-normal text-zinc-400">{meta.desc}</span>
                    </span>
                  </Button>
                ))}
              </div>
            </div>
          )}

          <div>
            <Label htmlFor="promo-name" className="mb-1.5 block text-xs text-zinc-700">
              活动名称
            </Label>
            <Input
              id="promo-name"
              className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 text-xs shadow-none focus-visible:ring-2 focus-visible:ring-zinc-400"
              placeholder="如:周年庆满减"
              value={form.name}
              onChange={(e) => set({ name: e.target.value })}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            {form.promoType === 'full_reduction' && (
              <div>
                <Label htmlFor="promo-threshold" className="mb-1.5 block text-xs text-zinc-700">
                  消费门槛(¥)
                </Label>
                <Input
                  id="promo-threshold"
                  className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 text-xs shadow-none focus-visible:ring-2 focus-visible:ring-zinc-400"
                  placeholder="如 300(订单满此金额生效)"
                  value={form.threshold}
                  onChange={(e) => set({ threshold: e.target.value })}
                />
              </div>
            )}
            <div>
              <Label htmlFor="promo-value" className="mb-1.5 block text-xs text-zinc-700">
                {form.promoType === 'full_reduction'
                  ? '减费金额(¥)'
                  : form.promoType === 'discount'
                    ? '折扣'
                    : '券面额(¥)'}
              </Label>
              <Input
                id="promo-value"
                className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 text-xs shadow-none focus-visible:ring-2 focus-visible:ring-zinc-400"
                placeholder={
                  form.promoType === 'discount'
                    ? '85 = 8.5 折'
                    : form.promoType === 'full_reduction'
                      ? '如 40'
                      : '如 15'
                }
                value={form.value}
                onChange={(e) => set({ value: e.target.value })}
              />
            </div>
            {form.promoType === 'coupon' && (
              <div>
                <Label htmlFor="promo-quota" className="mb-1.5 block text-xs text-zinc-700">
                  发放上限
                </Label>
                <Input
                  id="promo-quota"
                  className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 text-xs shadow-none focus-visible:ring-2 focus-visible:ring-zinc-400"
                  placeholder="留空 = 不限"
                  value={form.totalQuota}
                  onChange={(e) => set({ totalQuota: e.target.value })}
                />
              </div>
            )}
          </div>

          {scopeEditableFor(form.promoType) && (
            <div>
              <div className="mb-1.5 font-medium text-zinc-700">适用范围</div>
              <div className="flex gap-2">
                <Select value={form.scopeType} onValueChange={(v) => set({ scopeType: v, scopeValue: '' })}>
                  <SelectTrigger
                    aria-label="适用范围"
                    className="h-auto w-32 rounded-lg border-zinc-300 px-3 py-2 text-xs"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部商品</SelectItem>
                    <SelectItem value="spu">指定商品</SelectItem>
                  </SelectContent>
                </Select>
                {form.scopeType === 'spu' && (
                  <Select value={form.scopeValue} onValueChange={(v) => set({ scopeValue: v })}>
                    {/* 未选商品 = 空串受控值,走 SelectValue placeholder(占位项不可选) */}
                    <SelectTrigger
                      aria-label="适用商品"
                      className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 text-xs"
                    >
                      <SelectValue placeholder="选择商品…" />
                    </SelectTrigger>
                    <SelectContent>
                      {spus.map((s) => (
                        <SelectItem key={s.id} value={s.spu_code}>
                          {s.title}({s.spu_code})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>
            </div>
          )}

          <div>
            <div className="mb-1.5 font-medium text-zinc-700">有效期</div>
            <div className="flex items-center gap-2">
              <Input
                type="datetime-local"
                aria-label="开始时间"
                className="h-auto flex-1 rounded-lg border-zinc-300 px-3 py-2 text-xs shadow-none focus-visible:ring-2 focus-visible:ring-zinc-400"
                value={form.startAt}
                onChange={(e) => set({ startAt: e.target.value })}
              />
              <span className="text-zinc-400">至</span>
              <Input
                type="datetime-local"
                aria-label="结束时间"
                className="h-auto flex-1 rounded-lg border-zinc-300 px-3 py-2 text-xs shadow-none focus-visible:ring-2 focus-visible:ring-zinc-400"
                value={form.endAt}
                onChange={(e) => set({ endAt: e.target.value })}
                placeholder="留空 = 长期"
              />
            </div>
          </div>

          {/* 实时规则预览 + 口径注记 */}
          <div className="space-y-1 rounded-lg bg-zinc-50 px-3 py-2 text-[11px] text-zinc-500">
            {preview && (
              <div>
                规则预览:<span className="font-medium text-zinc-700">{preview}</span>
              </div>
            )}
            <div>
              优惠按整单金额计算;券型全员可领可用(引擎口径),发放上限控制总张数;下单结算自动应用属资金口径(20-D3)。
            </div>
          </div>

          {err && <div className="text-[11px] text-red-600">{err}</div>}
        </div>

        <DialogFooter className="gap-2 sm:gap-0 pt-3 border-t border-slate-100">
          <Button type="button" variant="outline" size="sm" onClick={onClose} className="text-xs cursor-pointer">
            取消
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={busy || !form.name.trim() || !form.value || (form.scopeType === 'spu' && !form.scopeValue)}
            onClick={() => void submit()}
            className="text-xs font-bold cursor-pointer"
          >
            {isEdit ? '保存' : '创建'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
