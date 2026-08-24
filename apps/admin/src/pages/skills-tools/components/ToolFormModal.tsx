import type React from 'react';
import { FormModal } from '../../../components/crud';
import type { SkillToolRecord } from '../types';

export interface ToolFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (e: React.FormEvent) => void;
  isCreate: boolean;
  formData: Partial<SkillToolRecord>;
  setFormData: (data: Partial<SkillToolRecord>) => void;
}

export function ToolFormModal({ isOpen, onClose, onSubmit, isCreate, formData, setFormData }: ToolFormModalProps) {
  return (
    <FormModal
      isOpen={isOpen}
      onClose={onClose}
      onSubmit={onSubmit}
      title={isCreate ? '注册新工具 / 技能 (Registry)' : `配置工具: ${formData.name}`}
      subtitle="配置工具的 JSON Schema 入参定义、执行端点与风控安全级别"
    >
      <div className="space-y-3.5">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">工具标识 (Unique ID)</label>
            <input
              type="text"
              required
              disabled={!isCreate}
              value={formData.id || ''}
              onChange={(e) => setFormData({ ...formData, id: e.target.value })}
              placeholder="如 queryInventory"
              className="w-full px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg font-mono disabled:opacity-60"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">工具类型</label>
            <select
              value={formData.type || 'openapi'}
              onChange={(e) => setFormData({ ...formData, type: e.target.value as any })}
              className="w-full px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg font-medium text-slate-700"
            >
              <option value="skill">SOP Skill 复合技能</option>
              <option value="native">Native 原生工具</option>
              <option value="openapi">OpenAPI 动态接入</option>
              <option value="mcp">MCP (Model Context Protocol)</option>
            </select>
          </div>
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">显示名称</label>
          <input
            type="text"
            required
            value={formData.name || ''}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            placeholder="如 商品库存实时查询 / 售后退款 SOP"
            className="w-full px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg"
          />
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">
            工具/技能功能详细描述 (Prompt Guidance)
          </label>
          <textarea
            required
            rows={3}
            value={formData.description || ''}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            placeholder="说明该工具的用途以及何时触发..."
            className="w-full px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg leading-relaxed"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">风控等级</label>
            <select
              value={formData.riskLevel || 'low'}
              onChange={(e) => setFormData({ ...formData, riskLevel: e.target.value as any })}
              className="w-full px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg"
            >
              <option value="low">低风险 (Low - 自动执行)</option>
              <option value="medium">中风险 (Medium - 记录日志)</option>
              <option value="high">高风险 (High - 敏感资金/操作)</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">免审金额阈值 (元, 可选)</label>
            <input
              type="number"
              min="0"
              step="0.01"
              value={formData.approvalThresholdAmount ?? ''}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  approvalThresholdAmount: e.target.value ? Number.parseFloat(e.target.value) : undefined,
                })
              }
              placeholder="超过该金额自动触发审批"
              className="w-full px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg"
            />
          </div>
        </div>
        <div className="flex items-center gap-2 pt-2">
          <input
            type="checkbox"
            id="hitl-check"
            checked={formData.requiresHitl ?? false}
            onChange={(e) => setFormData({ ...formData, requiresHitl: e.target.checked })}
            className="rounded text-slate-900"
          />
          <label htmlFor="hitl-check" className="text-xs font-semibold text-slate-700 cursor-pointer">
            强制触发 HITL 人工核准
          </label>
        </div>
      </div>
    </FormModal>
  );
}
