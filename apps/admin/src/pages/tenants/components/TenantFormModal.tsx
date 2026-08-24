import type React from "react";
import { FormModal } from "../../../components/crud";
import { Input, Label } from "ui";
import type { TenantRecord } from "../types";

export interface TenantFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (e: React.FormEvent) => void;
  isCreate: boolean;
  formData: Partial<TenantRecord>;
  setFormData: (data: Partial<TenantRecord>) => void;
}

export function TenantFormModal({
  isOpen,
  onClose,
  onSubmit,
  isCreate,
  formData,
  setFormData,
}: TenantFormModalProps) {
  return (
    <FormModal
      isOpen={isOpen}
      onClose={onClose}
      onSubmit={onSubmit}
      title={
        isCreate ? "新增商户租户 (Tenant)" : `编辑商户配置: ${formData.name}`
      }
      subtitle="配置商户基本属性、安全鉴权 API Key 及 SPI Webhook 回调地址"
    >
      <div className="space-y-3.5">
        <div>
          <Label className="block text-xs font-semibold text-slate-700 mb-1">
            商户 ID (Tenant Key)
          </Label>
          <Input
            type="text"
            required
            disabled={!isCreate}
            value={formData.id || ""}
            onChange={(e) => setFormData({ ...formData, id: e.target.value })}
            placeholder="如 nike, adidas, zara"
            className="w-full h-8 text-xs bg-slate-50 border-slate-200 font-mono disabled:opacity-60"
          />
        </div>
        <div>
          <Label className="block text-xs font-semibold text-slate-700 mb-1">
            商户全称
          </Label>
          <Input
            type="text"
            required
            value={formData.name || ""}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            placeholder="如 Nike 官方旗舰店"
            className="w-full h-8 text-xs bg-slate-50 border-slate-200"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="block text-xs font-semibold text-slate-700 mb-1">
              所属行业
            </Label>
            <Input
              type="text"
              value={formData.industry || ""}
              onChange={(e) =>
                setFormData({ ...formData, industry: e.target.value })
              }
              className="w-full h-8 text-xs bg-slate-50 border-slate-200"
            />
          </div>
          <div>
            <Label className="block text-xs font-semibold text-slate-700 mb-1">
              退款风控阈值 (元)
            </Label>
            <Input
              type="number"
              value={formData.refundLimit ?? 300}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  refundLimit: Number(e.target.value),
                })
              }
              className="w-full h-8 text-xs bg-slate-50 border-slate-200"
            />
          </div>
        </div>
        <div>
          <Label className="block text-xs font-semibold text-slate-700 mb-1">
            SPI Webhook 回调地址
          </Label>
          <Input
            type="url"
            value={formData.webhookUrl || ""}
            onChange={(e) =>
              setFormData({ ...formData, webhookUrl: e.target.value })
            }
            placeholder="https://api.merchant.com/spi/callback"
            className="w-full h-8 text-xs bg-slate-50 border-slate-200 font-mono"
          />
        </div>
        <div>
          <Label className="block text-xs font-semibold text-slate-700 mb-1">
            API Key (通信密钥)
          </Label>
          <Input
            type="text"
            value={formData.apiKey || ""}
            onChange={(e) =>
              setFormData({ ...formData, apiKey: e.target.value })
            }
            className="w-full h-8 text-xs bg-slate-50 border-slate-200 font-mono"
          />
        </div>
      </div>
    </FormModal>
  );
}
