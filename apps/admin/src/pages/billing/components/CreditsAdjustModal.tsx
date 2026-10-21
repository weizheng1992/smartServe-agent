import React, { useEffect, useState } from 'react';
import { Input, Label } from 'ui';
import { FormModal } from '../../../components/crud';
import { billingApi } from '../../../lib/api';
import { validateCreditAdjust } from '../credits';
import type { TenantBillingRecord } from '../types';

export interface CreditsAdjustModalProps {
  isOpen: boolean;
  onClose: () => void;
  record: TenantBillingRecord | null;
  /** 调整成功回调:携带服务端回读余额(businessId, balance),页面就地刷新积分列 */
  onSuccess: (businessId: string, balance: number | null) => void;
}

const DELTA_SEMANTIC = '正数 = 充值 · 负数 = 核减(1 次问询 = 1 积分)';

/** 积分调整弹窗(QuotaFormModal 同族:FormModal 壳 + errorMessage 窗内呈现)。
 *  delta 可负:核减穿零等服务端 400 由 body.error 诚实展示,不吞不装成功。 */
export function CreditsAdjustModal({ isOpen, onClose, record, onSuccess }: CreditsAdjustModalProps) {
  const [delta, setDelta] = useState('');
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 每次开窗重置表单(入口为逐行按钮,换目标商户必经关→开)
  useEffect(() => {
    if (isOpen) {
      setDelta('');
      setReason('');
      setError(null);
    }
  }, [isOpen]);

  const parsedDelta = Number(delta);
  const deltaFinite = delta.trim() !== '' && Number.isFinite(parsedDelta);
  const semantic =
    !deltaFinite || parsedDelta === 0
      ? null
      : parsedDelta > 0
        ? `充值 +${parsedDelta}`
        : `核减 ${parsedDelta}`;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!record || submitting) return;
    const invalid = validateCreditAdjust(delta, reason);
    if (invalid) {
      setError(invalid);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await billingApi.adjustCredits(record.businessId, Number(delta), reason.trim());
      if (!res.success) {
        // 业务/HTTP 错误体原样呈现(api.ts 收口语义),窗不关可改后重试
        setError(res.error || '积分调整失败');
        return;
      }
      onSuccess(record.businessId, res.data?.balance ?? null);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '网络通信异常,请检查后端网关是否已启动');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <FormModal
      isOpen={isOpen}
      onClose={onClose}
      onSubmit={handleSubmit}
      title={`调整积分: ${record?.tenantName || ''}`}
      subtitle="手动充值 / 核减商户共享积分池,写审计台账(operator 记平台管理员)"
      submitText="提交调整"
      isSubmitting={submitting}
      errorMessage={error}
    >
      <div className="space-y-3.5">
        <div>
          <Label className="mb-1 block text-xs font-semibold text-slate-700">商户租户</Label>
          <Input
            type="text"
            disabled
            value={record ? `${record.tenantName}(${record.businessId})` : ''}
            className="h-8 w-full border-slate-200 bg-slate-100 text-xs text-slate-600"
          />
        </div>
        <div>
          <Label className="mb-1 block text-xs font-semibold text-slate-700">调整数值(积分)</Label>
          <Input
            type="number"
            step="1"
            placeholder="如 500 充值 / -200 核减"
            value={delta}
            onChange={(e) => setDelta(e.target.value)}
            className="h-8 w-full border-slate-200 bg-slate-50 font-mono text-xs"
          />
          <div className="mt-1 flex items-center justify-between">
            <span className="text-[11px] text-slate-400">{DELTA_SEMANTIC}</span>
            {semantic && (
              <span
                className={`text-[11px] font-semibold ${parsedDelta > 0 ? 'text-emerald-600' : 'text-rose-600'}`}
              >
                {semantic}
              </span>
            )}
          </div>
        </div>
        <div>
          <Label className="mb-1 block text-xs font-semibold text-slate-700">调整原因(必填,入审计台账)</Label>
          <Input
            type="text"
            placeholder="如:双十一活动赠送 / 多扣回冲"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="h-8 w-full border-slate-200 bg-slate-50 text-xs"
          />
        </div>
      </div>
    </FormModal>
  );
}
