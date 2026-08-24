import type React from 'react';
import { FormModal } from '../../../components/crud';
import type { KnowledgeChunkRecord } from '../types';

export interface KnowledgeFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (e: React.FormEvent) => void;
  isCreate: boolean;
  formData: Partial<KnowledgeChunkRecord>;
  setFormData: (data: Partial<KnowledgeChunkRecord>) => void;
}

export function KnowledgeFormModal({
  isOpen,
  onClose,
  onSubmit,
  isCreate,
  formData,
  setFormData,
}: KnowledgeFormModalProps) {
  return (
    <FormModal
      isOpen={isOpen}
      onClose={onClose}
      onSubmit={onSubmit}
      title={isCreate ? '新增 RAG 知识切片' : `编辑知识切片: ${formData.docTitle}`}
      subtitle="为租户向量数据库录入最新的业务知识切片"
    >
      <div className="space-y-3.5">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">文档标题</label>
            <input
              type="text"
              required
              value={formData.docTitle || ''}
              onChange={(e) => setFormData({ ...formData, docTitle: e.target.value })}
              placeholder="如 Nike 退换货 SOP"
              className="w-full px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">归属商户</label>
            <select
              value={formData.businessId || 'nike'}
              onChange={(e) => setFormData({ ...formData, businessId: e.target.value })}
              className="w-full px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg font-medium text-slate-700"
            >
              <option value="nike">Nike 官方旗舰店</option>
              <option value="adidas">Adidas 运动专营</option>
              <option value="ecommerce">通用电商主站</option>
            </select>
          </div>
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">知识分类</label>
          <input
            type="text"
            value={formData.category || '售后政策'}
            onChange={(e) => setFormData({ ...formData, category: e.target.value })}
            className="w-full px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg"
          />
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">切片正文内容 (Markdown / Plaintext)</label>
          <textarea
            required
            rows={4}
            value={formData.content || ''}
            onChange={(e) => setFormData({ ...formData, content: e.target.value })}
            placeholder="输入该切片涵盖的详细业务事实与规则..."
            className="w-full px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg leading-relaxed font-mono"
          />
        </div>
      </div>
    </FormModal>
  );
}
