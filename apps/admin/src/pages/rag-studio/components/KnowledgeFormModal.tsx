import type React from 'react';
import { Input, Label, Textarea } from 'ui';
import { FormModal } from '../../../components/crud';
import { buildBusinessScopeOptions } from '../../../lib/businessScopes';
import { useAdminTenantStore } from '../../../store/tenantStore';
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
  // 归属商户 = 租户注册表 ∪ 平台内置业务域(此前硬编码三个演示租户,真实入驻租户选不了)
  const { tenants } = useAdminTenantStore();
  const businessOptions = buildBusinessScopeOptions(tenants);
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
            <Label className="block text-xs font-semibold text-slate-700 mb-1">文档标题</Label>
            <Input
              type="text"
              required
              value={formData.docTitle || ''}
              onChange={(e) => setFormData({ ...formData, docTitle: e.target.value })}
              placeholder="如 Nike 退换货 SOP"
              className="w-full h-8 text-xs bg-slate-50 border-slate-200"
            />
          </div>
          <div>
            <Label className="block text-xs font-semibold text-slate-700 mb-1">归属商户</Label>
            <select
              value={formData.businessId || 'ecommerce'}
              onChange={(e) => setFormData({ ...formData, businessId: e.target.value })}
              className="w-full h-8 px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-md font-medium text-slate-700 focus:outline-hidden focus:border-slate-400"
            >
              {businessOptions.map((opt) => (
                <option key={opt.id} value={opt.id}>
                  {opt.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div>
          <Label className="block text-xs font-semibold text-slate-700 mb-1">知识分类</Label>
          <select
            value={formData.category || 'product_knowledge'}
            onChange={(e) => setFormData({ ...formData, category: e.target.value })}
            className="w-full h-8 px-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-md font-medium text-slate-700 focus:outline-hidden focus:border-slate-400"
          >
            <option value="product_knowledge">商品知识 (product_knowledge)</option>
            <option value="store_info">门店信息 (store_info)</option>
            <option value="operation_guide">运营指南 (operation_guide)</option>
          </select>
        </div>
        <div>
          <Label className="block text-xs font-semibold text-slate-700 mb-1">切片正文内容 (Markdown / Plaintext)</Label>
          <Textarea
            required
            rows={4}
            value={formData.content || ''}
            onChange={(e) => setFormData({ ...formData, content: e.target.value })}
            placeholder="输入该切片涵盖的详细业务事实与规则..."
            className="w-full text-xs bg-slate-50 border-slate-200 leading-relaxed font-mono"
          />
        </div>
      </div>
    </FormModal>
  );
}
