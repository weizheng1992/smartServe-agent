import type React from "react";
import { FormModal } from "../../../components/crud";
import { Input, Label } from "ui";
import type { TenantBillingRecord } from "../types";

export interface QuotaFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (e: React.FormEvent) => void;
  selectedItem: TenantBillingRecord | null;
  formData: Partial<TenantBillingRecord>;
  setFormData: (data: Partial<TenantBillingRecord>) => void;
}

export function QuotaFormModal({
  isOpen,
  onClose,
  onSubmit,
  selectedItem,
  formData,
  setFormData,
}: QuotaFormModalProps) {
  return (
    <FormModal
      isOpen={isOpen}
      onClose={onClose}
      onSubmit={onSubmit}
      title={`调整配额上限: ${selectedItem?.tenantName}`}
      subtitle="修改租户月度 Token 最大使用配额与预警水位"
    >
      <div className="space-y-3.5">
        <div>
          <Label className="block text-xs font-semibold text-slate-700 mb-1">
            商户租户
          </Label>
          <Input
            type="text"
            disabled
            value={selectedItem?.tenantName || ""}
            className="w-full h-8 text-xs bg-slate-100 border-slate-200 text-slate-600"
          />
        </div>
        <div>
          <Label className="block text-xs font-semibold text-slate-700 mb-1">
            月度 Token 配额上限 (Tokens)
          </Label>
          <Input
            type="number"
            step="500000"
            value={formData.monthlyLimitTokens ?? 5000000}
            onChange={(e) =>
              setFormData({
                ...formData,
                monthlyLimitTokens: Number(e.target.value),
              })
            }
            className="w-full h-8 text-xs bg-slate-50 border-slate-200 font-mono"
          />
        </div>
      </div>
    </FormModal>
  );
}
