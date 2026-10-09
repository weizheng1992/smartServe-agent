import { type Spu, api } from '@/lib/api';
import { useEffect, useState } from 'react';
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

/** Radix SelectItem 禁空串:负责人「未分配」的哨兵值(onValueChange 单点映射回 '')。 */
const UNSET = '__unset__';

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

  // 打开时按目标 SPU 预填(仿 promo-dialog 的 open 重置范式;本组件随行挂载)
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

  async function save() {
    const b = await api.products.update(spu.id, {
      title: form.title,
      price: Number(form.price),
      stock: Number(form.stock),
      ownerId: form.ownerId,
    });
    onMsg(b.success ? '✓ 已保存' : `失败:${b.message}`);
    if (b.success) onClose();
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md rounded-xl border-zinc-200 text-zinc-900 shadow-xl">
        <DialogHeader className="pb-3 border-b border-zinc-100">
          <DialogTitle className="text-base font-bold text-zinc-900">编辑商品 · {spu.title}</DialogTitle>
          <p className="mt-1 text-xs text-zinc-500">
            {spu.spu_code} · {spu.category} · 类目创建后不可改
          </p>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto py-4 text-xs">
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
            <Select
              value={form.ownerId || UNSET}
              onValueChange={(v) => setForm({ ...form, ownerId: v === UNSET ? '' : v })}
            >
              {/* Radix SelectItem 禁空串:真·可选空值走 __unset__ 哨兵,提交前已映射回 '' */}
              <SelectTrigger aria-label="负责人" className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={UNSET}>未分配</SelectItem>
                {staffOptions.map((o) => (
                  <SelectItem key={o.id} value={o.id}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter className="gap-2 pt-3 sm:gap-0 border-t border-zinc-100">
          <Button type="button" variant="outline" size="sm" onClick={onClose} className="text-xs cursor-pointer">
            取消
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={!form.title}
            onClick={() => void save()}
            className="text-xs font-bold cursor-pointer"
          >
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
