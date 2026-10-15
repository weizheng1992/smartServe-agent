import { FormDialogShell } from '@/components/form-dialog-shell';
import { OptionalSelect } from '@/components/optional-select';
import { type Spu, api, errMsgOf } from '@/lib/api';
import { useEffect, useState } from 'react';
import { Input, Label } from 'ui';

interface Props {
  spu: Spu;
  onMsg: (m: string) => void;
  onClose: () => void;
}

/** 编辑商品弹窗:标题/售价/库存/负责人 一次改齐(类目创建后不可改,不展示)。 */
export function SpuEditDialog({ spu, onMsg, onClose }: Props) {
  const [form, setForm] = useState({ title: '', price: '', stock: '', ownerId: '' });
  // 负责人选项(全员;停用员工保留显示 —— 仍可在职员工里改派)
  const [staffOptions, setStaffOptions] = useState<Array<{ id: string; label: string }>>([]);

  // 打开时按目标 SPU 预填(随行挂载,挂载即初值)
  useEffect(() => {
    setForm({
      title: spu.title,
      price: String(spu.price),
      stock: String(spu.stock),
      ownerId: spu.ownerId ?? '',
    });
  }, [spu]);

  useEffect(() => {
    void api.staffList().then((res) => {
      setStaffOptions(
        (res.staff || []).map((s) => ({
          id: s.id,
          label: `${s.displayName}${s.dept ? `(${s.dept}${s.level ? `·${s.level}` : ''})` : ''}`,
        })),
      );
    });
  }, []);

  return (
    <FormDialogShell
      title={`编辑商品 · ${spu.title}`}
      subtitle={`${spu.spu_code} · ${spu.category} · 类目创建后不可改`}
      maxWidth="max-w-md"
      submitLabel="保存"
      submitDisabled={!form.title}
      onClose={onClose}
      onSubmit={async () => {
        const b = await api.products.update(spu.id, {
          title: form.title,
          price: Number(form.price),
          stock: Number(form.stock),
          ownerId: form.ownerId,
        });
        if (!b.success) return errMsgOf(b);
        onMsg('✓ 已保存');
        return null;
      }}
    >
      <div>
        <Label htmlFor="edit-spu-title" className="mb-1.5 block text-zinc-700">
          商品标题
        </Label>
        <Input
          id="edit-spu-title"
          className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label htmlFor="edit-spu-price" className="mb-1.5 block text-zinc-700">
            售价(¥)
          </Label>
          <Input
            id="edit-spu-price"
            className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
            value={form.price}
            onChange={(e) => setForm({ ...form, price: e.target.value })}
          />
        </div>
        <div>
          <Label htmlFor="edit-spu-stock" className="mb-1.5 block text-zinc-700">
            库存
          </Label>
          <Input
            id="edit-spu-stock"
            className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
            value={form.stock}
            onChange={(e) => setForm({ ...form, stock: e.target.value })}
          />
        </div>
      </div>
      <div>
        <Label className="mb-1.5 block text-zinc-700">负责人</Label>
        {/* 哨兵生命周期封在 OptionalSelect(onChange 直收 '') */}
        <OptionalSelect
          value={form.ownerId}
          onChange={(v) => setForm({ ...form, ownerId: v })}
          options={staffOptions.map((o) => ({ value: o.id, label: o.label }))}
          emptyLabel="未分配"
          ariaLabel="负责人"
          className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2"
        />
      </div>
    </FormDialogShell>
  );
}
