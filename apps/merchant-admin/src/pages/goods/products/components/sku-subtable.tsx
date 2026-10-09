import {
  DenseTable,
  DenseTableBody,
  DenseTableCell,
  DenseTableHead,
  DenseTableHeader,
  DenseTableRow,
} from '@/components/dense-table';
import { type Sku, type Spu, api } from '@/lib/api';
import { useCallback, useEffect, useState } from 'react';
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, Input, Label } from 'ui';

/** 通用小弹窗外壳:字段区两枚 Input(价格/库存 或 标题/价格/库存)。 */
function SkuFormDialog({
  title,
  subtitle,
  submitLabel,
  submitDisabled,
  onSubmit,
  onClose,
  fields,
}: {
  title: string;
  subtitle: string;
  submitLabel: string;
  submitDisabled: boolean;
  onSubmit: () => void;
  onClose: () => void;
  fields: Array<{ id: string; label: string; placeholder: string; value: string; onChange: (v: string) => void }>;
}) {
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm rounded-xl border-zinc-200 text-zinc-900 shadow-xl">
        <DialogHeader className="pb-3 border-b border-zinc-100">
          <DialogTitle className="text-base font-bold text-zinc-900">{title}</DialogTitle>
          <p className="mt-1 text-xs text-zinc-500">{subtitle}</p>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto py-4 text-xs">
          {fields.map((f) => (
            <div key={f.id}>
              <Label htmlFor={f.id} className="mb-1.5 block text-zinc-700">
                {f.label}
              </Label>
              <Input
                id={f.id}
                className="h-auto w-full rounded-lg border-zinc-300 px-3 py-2 shadow-none focus-visible:ring-0"
                placeholder={f.placeholder}
                value={f.value}
                onChange={(e) => f.onChange(e.target.value)}
              />
            </div>
          ))}
        </div>
        <DialogFooter className="gap-2 pt-3 sm:gap-0 border-t border-zinc-100">
          <Button type="button" variant="outline" size="sm" onClick={onClose} className="text-xs cursor-pointer">
            取消
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={submitDisabled}
            onClick={onSubmit}
            className="text-xs font-bold cursor-pointer"
          >
            {submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface Props {
  spu: Spu;
  onMsg: (m: string) => void;
}

const EMPTY_NEW = { skuTitle: '', price: '', stock: '' };

/** SKU 明细子表(承接 SPU 行展开):自持明细数据与新增/改价/删除,
 *  挂载即拉取;删除受"已有成交不可删"服务端护栏。 */
export function SkuSubTable({ spu, onMsg }: Props) {
  const [skus, setSkus] = useState<Sku[]>([]);
  const [creating, setCreating] = useState(false);
  const [priceEdit, setPriceEdit] = useState<Sku | null>(null);

  const loadSkus = useCallback(async () => {
    setSkus((await api.products.listSkus(spu.id)).skus || []);
  }, [spu.id]);
  useEffect(() => {
    void loadSkus();
  }, [loadSkus]);

  async function createSku(newSku: { skuTitle: string; price: string; stock: string }, close: () => void) {
    const b = await api.products.createSku(spu.id, newSku);
    onMsg(b.success ? `✓ SKU ${b.skuCode} 已新增` : `失败:${b.message}`);
    if (b.success) {
      close();
      void loadSkus();
    }
  }

  async function saveSku(sku: Sku, patch: { price: string; stock: string }, close: () => void) {
    const b = await api.products.updateSku(sku.id, { price: Number(patch.price), stock: Number(patch.stock) });
    onMsg(b.success ? '✓ SKU 已保存' : `失败:${b.message}`);
    if (b.success) {
      close();
      void loadSkus();
    }
  }

  async function deleteSku(skuId: string) {
    const b = await api.products.removeSku(skuId);
    onMsg(b.success ? '✓ 已删除' : `失败:${b.message}`);
    void loadSkus();
  }

  return (
    <div>
      <div className="text-[11px] font-semibold text-zinc-500 mb-2">SKU 明细 · {spu.spu_code}</div>
      {/* 嵌套在 SPU 展开行内:!overflow-visible 关闭包裹层滚动,密度沿用外层极紧凑风 */}
      <DenseTable className="!overflow-visible text-[12px]">
        <DenseTableHeader>
          <DenseTableRow className="hover:bg-transparent">
            <DenseTableHead className="py-1 pr-4 text-[12px] text-zinc-400">SKU 编码</DenseTableHead>
            <DenseTableHead className="py-1 pr-4 text-[12px] text-zinc-400">价格</DenseTableHead>
            <DenseTableHead className="py-1 pr-4 text-[12px] text-zinc-400">库存</DenseTableHead>
            <DenseTableHead className="py-1 text-[12px] text-zinc-400">操作</DenseTableHead>
          </DenseTableRow>
        </DenseTableHeader>
        <DenseTableBody>
          {skus.map((k) => (
            <DenseTableRow key={k.id} className="border-b-0">
              <DenseTableCell className="py-1 pr-4 pl-0 font-mono">{k.sku_code}</DenseTableCell>
              <DenseTableCell className="py-1 pr-4 pl-0">¥{k.price}</DenseTableCell>
              <DenseTableCell className="py-1 pr-4 pl-0">{k.stock}</DenseTableCell>
              <DenseTableCell className="py-1 pl-0">
                <Button size="sm" variant="ghost" onClick={() => setPriceEdit(k)}>
                  改价/库存
                </Button>
                <Button size="sm" variant="ghost" className="text-rose-600" onClick={() => void deleteSku(k.id)}>
                  删除
                </Button>
              </DenseTableCell>
            </DenseTableRow>
          ))}
        </DenseTableBody>
      </DenseTable>
      {priceEdit && (
        <PriceEditDialog sku={priceEdit} onMsg={onMsg} onClose={() => setPriceEdit(null)} onSubmit={saveSku} />
      )}
      <div className="mt-2">
        <Button size="sm" variant="outline" onClick={() => setCreating(true)}>
          + 新增 SKU
        </Button>
      </div>
      {creating && <SkuCreateDialog spu={spu} onMsg={onMsg} onClose={() => setCreating(false)} onSubmit={createSku} />}
    </div>
  );
}

/** 改价/库存弹窗(行内「改价/库存」唤起,保存走 api.products.updateSku)。 */
function PriceEditDialog({
  sku,
  onMsg,
  onClose,
  onSubmit,
}: {
  sku: Sku;
  onMsg: (m: string) => void;
  onClose: () => void;
  onSubmit: (sku: Sku, patch: { price: string; stock: string }, close: () => void) => Promise<void>;
}) {
  const [patch, setPatch] = useState({ price: String(sku.price), stock: String(sku.stock) });
  return (
    <SkuFormDialog
      title={`改价/库存 · ${sku.sku_code}`}
      subtitle={sku.sku_title || ''}
      submitLabel="保存"
      submitDisabled={false}
      onSubmit={() => void onSubmit(sku, patch, onClose)}
      onClose={onClose}
      fields={[
        {
          id: 'sku-price',
          label: '价格(¥)',
          placeholder: '如 329',
          value: patch.price,
          onChange: (v) => setPatch({ ...patch, price: v }),
        },
        {
          id: 'sku-stock',
          label: '库存',
          placeholder: '如 50',
          value: patch.stock,
          onChange: (v) => setPatch({ ...patch, stock: v }),
        },
      ]}
    />
  );
}

/** 新增 SKU 弹窗(标题/价格/库存;价格必填,与原内联条同口径)。 */
function SkuCreateDialog({
  spu,
  onMsg,
  onClose,
  onSubmit,
}: {
  spu: Spu;
  onMsg: (m: string) => void;
  onClose: () => void;
  onSubmit: (newSku: { skuTitle: string; price: string; stock: string }, close: () => void) => Promise<void>;
}) {
  const [form, setForm] = useState(EMPTY_NEW);
  return (
    <SkuFormDialog
      title={`新增 SKU · ${spu.spu_code}`}
      subtitle={`挂在「${spu.title}」下;标题/价格必填`}
      submitLabel="新增"
      submitDisabled={!form.skuTitle || !form.price}
      onSubmit={() => void onSubmit(form, onClose)}
      onClose={onClose}
      fields={[
        {
          id: 'new-sku-title',
          label: 'SKU 标题',
          placeholder: '如:红 42',
          value: form.skuTitle,
          onChange: (v) => setForm({ ...form, skuTitle: v }),
        },
        {
          id: 'new-sku-price',
          label: '价格(¥)',
          placeholder: '如 329',
          value: form.price,
          onChange: (v) => setForm({ ...form, price: v }),
        },
        {
          id: 'new-sku-stock',
          label: '库存',
          placeholder: '默认同 SPU',
          value: form.stock,
          onChange: (v) => setForm({ ...form, stock: v }),
        },
      ]}
    />
  );
}
