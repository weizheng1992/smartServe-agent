import { api } from '@/lib/api';
import { useState } from 'react';
import {
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from 'ui';

export const CATEGORIES = [
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
  const [form, setForm] = useState({ title: '', category: CATEGORIES[0], price: '', stock: '10' });

  async function create() {
    const b = await api.products.create({
      title: form.title,
      category: form.category,
      price: Number(form.price),
      stock: Number(form.stock),
    });
    onMsg(b.success ? `✓ 已上架「${form.title}」(${b.spuCode})` : `失败:${b.message}`);
    if (b.success) onClose();
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md rounded-xl border-zinc-200 text-zinc-900 shadow-xl">
        <DialogHeader className="pb-3 border-b border-zinc-100">
          <DialogTitle className="text-base font-bold text-zinc-900">新增商品</DialogTitle>
          <p className="mt-1 text-xs text-zinc-500">上架即建 SPU + 默认 SKU;标题与售价必填</p>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto py-4 text-xs">
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
                {CATEGORIES.map((c) => (
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
        </div>
        <DialogFooter className="gap-2 pt-3 sm:gap-0 border-t border-zinc-100">
          <Button type="button" variant="outline" size="sm" onClick={onClose} className="text-xs cursor-pointer">
            取消
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={!form.title || !form.price}
            onClick={() => void create()}
            className="text-xs font-bold cursor-pointer"
          >
            上架
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
