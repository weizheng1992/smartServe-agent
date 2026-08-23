import React from "react";
import { FormModal } from "../../../components/crud";
import type { GuardrailRuleRecord } from "../types";

export interface GuardrailFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (e: React.FormEvent) => void;
  isCreate: boolean;
  selectedItem: GuardrailRuleRecord | null;
  formData: Partial<GuardrailRuleRecord>;
  setFormData: (data: Partial<GuardrailRuleRecord>) => void;
}

export function GuardrailFormModal({
  isOpen,
  onClose,
  onSubmit,
  isCreate,
  selectedItem,
  formData,
  setFormData,
}: GuardrailFormModalProps) {
  return (
    <FormModal
      isOpen={isOpen}
      onClose={onClose}
      onSubmit={onSubmit}
      title={
        isCreate
          ? "添加安全合规围栏规则"
          : `编辑安全规则: ${selectedItem?.ruleName}`
      }
      subtitle="定义输入过滤、输出脱敏或 SQL 沙箱防御策略"
    >
      <div className="space-y-3.5">
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">
            规则名称
          </label>
          <input
            type="text"
            required
            value={formData.ruleName || ""}
            onChange={(e) =>
              setFormData({ ...formData, ruleName: e.target.value })
            }
            placeholder="如 手机号/银行卡脱敏规则"
            className="w-full px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              防护类型
            </label>
            <select
              value={formData.ruleType || "sensitive_keyword"}
              onChange={(e) =>
                setFormData({ ...formData, ruleType: e.target.value as any })
              }
              className="w-full px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg"
            >
              <option value="sensitive_keyword">
                敏感信息与隐私 (Privacy)
              </option>
              <option value="sql_injection">
                SQL 注入防线 (SQL Injection)
              </option>
              <option value="prompt_leakage">Prompt 防越狱/防泄露</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              拦截响应动作
            </label>
            <select
              value={formData.action || "block"}
              onChange={(e) =>
                setFormData({ ...formData, action: e.target.value as any })
              }
              className="w-full px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg"
            >
              <option value="block">直接拦截 (Block)</option>
              <option value="mask">脱敏掩码 (Mask)</option>
              <option value="warn">安全告警 (Warn)</option>
              <option value="escalate_hitl">升级人工客服 (Escalate)</option>
            </select>
          </div>
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">
            匹配正则表达式 / 关键词
          </label>
          <textarea
            required
            rows={3}
            value={formData.pattern || ""}
            onChange={(e) =>
              setFormData({ ...formData, pattern: e.target.value })
            }
            placeholder="如 (\\d{16,19}) 或 敏感词表"
            className="w-full px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg font-mono"
          />
        </div>
      </div>
    </FormModal>
  );
}
