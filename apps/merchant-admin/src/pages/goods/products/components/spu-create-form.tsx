import { FormDialogShell } from '@/components/form-dialog-shell';
import { api, errMsgOf } from '@/lib/api';
import { useEffect, useState } from 'react';
import { Input, Label, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from 'ui';

/** 品类闭集降级面(真源在服务端注册表,挂载时经 ownerMappings.list 拉取;
 *  此前手写数组为唯一真源,服务端品类变更在此静默滞后 —— 2026-10-15 候选③收口)。
 *  品类闭集真源现寄居 owner-mappings 注册表属临时耦合,应另立商品域端点(后端票)。 */
export const CATEGORIES_FALLBACK = [
  '户外机能',
  '潮流T恤',
  '下装裤类',
  '潮流鞋靴',
  '背包收纳',
  '露营装备',
  '衬衫',
  '配饰',
  '运动配件',
];

interface Props {
  onMsg: (m: string) => void;
  onClose: () => void;
}

/** 新增商品弹窗(上架即建 SPU + 默认 SKU)。 */
export function SpuCreateDialog({ onMsg, onClose }: Props) {
  const [form, setForm] = useState({ title: '', category: CATEGORIES_FALLBACK[0], price: '', stock: '10' });
  const [categories, setCategories] = useState<string[]>(CATEGORIES_FALLBACK);

  // 品类闭集以服务端注册表为真源(拉取失败诚实降级本地闭集,不阻断建品)
  useEffect(() => {
    void api.ownerMappings
      .list()
      .then((r) => {
        if (r.categories?.length) setCategories(r.categories);
      })
      .catch(() => {});
  }, []);

  return (
    <FormDialogShell
      title="新增商品"
      subtitle="上架即建 SPU + 默认 SKU;标题与售价必填"
      maxWidth="max-w-md"
      submitLabel="上架"
      submitDisabled={!form.title || !form.price}
      onClose={onClose}
      onSubmit={async () => {
        const b = await api.products.create({
          title: form.title,
          category: form.category,
          price: Number(form.price),
          stock: Number(form.stock),
        });
        if (!b.success) return errMsgOf(b);
        onMsg(`✓ 已上架「${form.title}」(${b.spuCode})`);
        return null;
      }}
    >
      <div>
        <Label htmlFor="spu-title" className="mb-1.5 block text-zinc-700">
          商品标题
        </Label>
        <Input
          id="spu-title"
          className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
          placeholder="如:极光防晒皮肤衣"
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
        />
      </div>
      <div>
        <Label className="mb-1.5 block text-zinc-700">类目</Label>
        <Select value={form.category} onValueChange={(v) => setForm({ ...form, category: v })}>
          <SelectTrigger aria-label="类目" className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {categories.map((c) => (
              <SelectItem key={c} value={c}>
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label htmlFor="spu-price" className="mb-1.5 block text-zinc-700">
            售价(¥)
          </Label>
          <Input
            id="spu-price"
            className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
            placeholder="如 329"
            value={form.price}
            onChange={(e) => setForm({ ...form, price: e.target.value })}
          />
        </div>
        <div>
          <Label htmlFor="spu-stock" className="mb-1.5 block text-zinc-700">
            库存
          </Label>
          <Input
            id="spu-stock"
            className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
            placeholder="默认 10"
            value={form.stock}
            onChange={(e) => setForm({ ...form, stock: e.target.value })}
          />
        </div>
      </div>
    </FormDialogShell>
  );
}
