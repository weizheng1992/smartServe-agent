import {
  DenseTable,
  DenseTableBody,
  DenseTableCell,
  DenseTableHead,
  DenseTableHeader,
  DenseTableRow,
} from '@/components/dense-table';
import { FormDialogShell } from '@/components/form-dialog-shell';
import { type Sku, type Spu, api, errMsgOf } from '@/lib/api';
import { useCallback, useEffect, useState } from 'react';
import { Button, Input, Label } from 'ui';

/** 通用小弹窗外壳(候选④):chrome/footer/busy 收口到 FormDialogShell,
 *  本件只剩 fields 数组这一层薄特化(onSubmit 走壳契约:成功 null、失败文案留窗内)。 */
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
  onSubmit: () => Promise<string | null>;
  onClose: () => void;
  fields: Array<{ id: string; label: string; placeholder: string; value: string; onChange: (v: string) => void }>;
}) {
  return (
    <FormDialogShell
      title={title}
      subtitle={subtitle}
      submitLabel={submitLabel}
      submitDisabled={submitDisabled}
      onSubmit={onSubmit}
      onClose={onClose}
    >
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
    </FormDialogShell>
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

  // 壳契约:成功 null(壳自动关窗),失败文案留窗内
  async function createSku(newSku: { skuTitle: string; price: string; stock: string }) {
    const b = await api.products.createSku(spu.id, newSku);
    if (!b.success) return errMsgOf(b);
    onMsg(`✓ SKU ${b.skuCode} 已新增`);
    void loadSkus();
    return null;
  }

  async function saveSku(sku: Sku, patch: { price: string; stock: string }) {
    const b = await api.products.updateSku(sku.id, { price: Number(patch.price), stock: Number(patch.stock) });
    if (!b.success) return errMsgOf(b);
    onMsg('✓ SKU 已保存');
    void loadSkus();
    return null;
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
        <PriceEditDialog
          sku={priceEdit}
          onClose={() => setPriceEdit(null)}
          onSubmit={(patch) => saveSku(priceEdit, patch)}
        />
      )}
      <div className="mt-2">
        <Button size="sm" variant="outline" onClick={() => setCreating(true)}>
          + 新增 SKU
        </Button>
      </div>
      {creating && (
        <SkuCreateDialog spu={spu} onClose={() => setCreating(false)} onSubmit={(form) => createSku(form)} />
      )}
    </div>
  );
}

/** 改价/库存弹窗(行内「改价/库存」唤起,保存走 api.products.updateSku)。 */
function PriceEditDialog({
  sku,
  onClose,
  onSubmit,
}: {
  sku: Sku;
  onClose: () => void;
  onSubmit: (patch: { price: string; stock: string }) => Promise<string | null>;
}) {
  const [patch, setPatch] = useState({ price: String(sku.price), stock: String(sku.stock) });
  return (
    <SkuFormDialog
      title={`改价/库存 · ${sku.sku_code}`}
      subtitle={sku.sku_title || ''}
      submitLabel="保存"
      submitDisabled={false}
      onSubmit={() => onSubmit(patch)}
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
  onClose,
  onSubmit,
}: {
  spu: Spu;
  onClose: () => void;
  onSubmit: (newSku: { skuTitle: string; price: string; stock: string }) => Promise<string | null>;
}) {
  const [form, setForm] = useState(EMPTY_NEW);
  return (
    <SkuFormDialog
      title={`新增 SKU · ${spu.spu_code}`}
      subtitle={`挂在「${spu.title}」下;标题/价格必填`}
      submitLabel="新增"
      submitDisabled={!form.skuTitle || !form.price}
      onSubmit={() => onSubmit(form)}
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
