import type React from "react";
import { FormModal } from "../../../components/crud";
import { Input, Textarea, Label } from "ui";
import type { PersonaRecord } from "../types";

export interface PersonaFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (e: React.FormEvent) => void;
  isCreate: boolean;
  formData: Partial<PersonaRecord>;
  setFormData: (data: Partial<PersonaRecord>) => void;
}

export function PersonaFormModal({
  isOpen,
  onClose,
  onSubmit,
  isCreate,
  formData,
  setFormData,
}: PersonaFormModalProps) {
  return (
    <FormModal
      isOpen={isOpen}
      onClose={onClose}
      onSubmit={onSubmit}
      title={isCreate ? "录入长期画像记忆 (Persona Fact)" : "编辑画像记忆事实"}
      subtitle="为指定用户构建长程对话偏好与业务属性，Agent 对话时将自动检索注入 Context"
    >
      <div className="space-y-3.5">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="block text-xs font-semibold text-slate-700 mb-1">
              用户 ID
            </Label>
            <Input
              type="text"
              required
              value={formData.userId || ""}
              onChange={(e) =>
                setFormData({ ...formData, userId: e.target.value })
              }
              placeholder="如 u_vip_881"
              className="w-full h-8 text-xs bg-slate-50 border-slate-200 font-mono"
            />
          </div>
          <div>
            <Label className="block text-xs font-semibold text-slate-700 mb-1">
              归属商户
            </Label>
            <select
              value={formData.businessId || "nike"}
              onChange={(e) =>
                setFormData({ ...formData, businessId: e.target.value })
              }
              className="w-full h-8 px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-md font-medium text-slate-700 focus:outline-hidden focus:border-slate-400"
            >
              <option value="nike">Nike 官方旗舰店</option>
              <option value="adidas">Adidas 运动专营</option>
              <option value="ecommerce">通用电商主站</option>
            </select>
          </div>
        </div>
        <div>
          <Label className="block text-xs font-semibold text-slate-700 mb-1">
            长程事实记忆文本 (Fact)
          </Label>
          <Textarea
            required
            rows={3}
            value={formData.fact || ""}
            onChange={(e) => setFormData({ ...formData, fact: e.target.value })}
            placeholder="例如：尺码偏好 42.5 码，偏好顺丰次日达发货..."
            className="w-full text-xs bg-slate-50 border-slate-200 leading-relaxed"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="block text-xs font-semibold text-slate-700 mb-1">
              置信度 (0.0 - 1.0)
            </Label>
            <Input
              type="number"
              step="0.05"
              min="0"
              max="1"
              value={formData.confidence ?? 0.9}
              onChange={(e) =>
                setFormData({ ...formData, confidence: Number(e.target.value) })
              }
              className="w-full h-8 text-xs bg-slate-50 border-slate-200"
            />
          </div>
          <div>
            <Label className="block text-xs font-semibold text-slate-700 mb-1">
              记忆状态
            </Label>
            <select
              value={formData.status || "approved"}
              onChange={(e) =>
                setFormData({ ...formData, status: e.target.value as any })
              }
              className="w-full h-8 px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-md text-slate-700 focus:outline-hidden focus:border-slate-400"
            >
              <option value="approved">已生效 (Approved)</option>
              <option value="pending">待核实 (Pending)</option>
              <option value="rejected">已废弃 (Rejected)</option>
            </select>
          </div>
        </div>
      </div>
    </FormModal>
  );
}
