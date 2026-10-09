import {
  DenseTable,
  DenseTableBody,
  DenseTableCell,
  DenseTableHead,
  DenseTableHeader,
  DenseTableRow,
} from '@/components/dense-table';
import { type Spu, api } from '@/lib/api';
import { setSelectionKind } from '@/lib/page-context';
import { Fragment, useEffect, useState } from 'react';
import { Button, Checkbox } from 'ui';
import { SkuSubTable } from './sku-subtable';
import { SpuEditDialog } from './spu-edit-dialog';

interface Props {
  spus: Spu[];
  onMsg: (m: string) => void;
  onChanged: () => void;
  /** 「+ 新增商品」入口归页面页头,表格上报唤起 */
  onCreate?: () => void;
}

/** SPU 列表:勾选→PageContext(spu 类,对话实时联动);编辑走 SpuEditDialog 弹窗
 *  (标题/售价/库存/负责人一次改齐)、上/下架、删除(订单引用护栏在服务端)、
 *  展开 SKU 子表。展开态/编辑弹窗态为本组件局部状态。 */
export function SpuTable({ spus, onMsg, onChanged, onCreate }: Props) {
  const [editSpu, setEditSpu] = useState<Spu | null>(null);
  const [openSkus, setOpenSkus] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  // 负责人选项(全员;停用员工保留显示 —— 仍可在职员工里改派)
  const [staffOptions, setStaffOptions] = useState<Array<{ id: string; label: string }>>([]);

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

  const staffLabel = (id: string | null) => staffOptions.find((s) => s.id === id)?.label ?? null;

  function toggleSelect(code: string) {
    const next = selected.includes(code) ? selected.filter((x) => x !== code) : [...selected, code];
    setSelected(next);
    const titles = Object.fromEntries(spus.filter((s) => next.includes(s.spu_code)).map((s) => [s.spu_code, s.title]));
    setSelectionKind('spu', next, titles);
  }

  async function toggleStatus(s: Spu) {
    const res = await api.products.update(s.id, { status: s.status === 'ON_SALE' ? 'OFF_SALE' : 'ON_SALE' });
    onMsg(res.success ? `✓ 「${s.title}」已${s.status === 'ON_SALE' ? '下架' : '上架'}` : '操作失败');
    onChanged();
  }

  async function remove(s: Spu) {
    const b = await api.products.remove(s.id);
    onMsg(b.success ? `✓ 已删除「${s.title}」` : `失败:${b.message}`);
    onChanged();
  }

  function toggleSkus(s: Spu) {
    setOpenSkus(openSkus === s.id ? null : s.id);
  }

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
      <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3 text-sm font-medium">
        <span>商品列表</span>
        {onCreate && (
          <Button size="sm" onClick={onCreate}>
            + 新增商品
          </Button>
        )}
      </div>
      <DenseTable>
        <DenseTableHeader>
          <DenseTableRow className="border-b border-zinc-100 hover:bg-transparent">
            <DenseTableHead className="w-10 px-3" />
            <DenseTableHead>商品</DenseTableHead>
            <DenseTableHead>品类</DenseTableHead>
            <DenseTableHead>售价</DenseTableHead>
            <DenseTableHead>库存</DenseTableHead>
            <DenseTableHead>负责人</DenseTableHead>
            <DenseTableHead>状态</DenseTableHead>
            <DenseTableHead>操作</DenseTableHead>
          </DenseTableRow>
        </DenseTableHeader>
        <DenseTableBody>
          {spus.map((s) => (
            <Fragment key={s.id}>
              <DenseTableRow>
                <DenseTableCell className="px-3">
                  <Checkbox
                    aria-label={`选择商品 ${s.title}`}
                    checked={selected.includes(s.spu_code)}
                    onCheckedChange={() => toggleSelect(s.spu_code)}
                  />
                </DenseTableCell>
                <DenseTableCell>{s.title}</DenseTableCell>
                <DenseTableCell>{s.category}</DenseTableCell>
                <DenseTableCell>¥{s.price}</DenseTableCell>
                <DenseTableCell>{s.stock}</DenseTableCell>
                <DenseTableCell className="text-xs">
                  {staffLabel(s.ownerId) ?? <span className="text-zinc-400">未分配</span>}
                </DenseTableCell>
                <DenseTableCell>
                  <span className={s.status === 'ON_SALE' ? 'text-emerald-600' : 'text-zinc-400'}>
                    {s.status === 'ON_SALE' ? '在售' : '下架'}
                  </span>
                </DenseTableCell>
                <DenseTableCell>
                  <div className="flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => setEditSpu(s)}>
                      编辑
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => void toggleStatus(s)}>
                      {s.status === 'ON_SALE' ? '下架' : '上架'}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => toggleSkus(s)}>
                      SKU
                    </Button>
                    <Button size="sm" variant="ghost" className="text-rose-600" onClick={() => void remove(s)}>
                      删除
                    </Button>
                  </div>
                </DenseTableCell>
              </DenseTableRow>
              {openSkus === s.id && (
                <DenseTableRow className="bg-zinc-50/60">
                  <DenseTableCell colSpan={8} className="px-6 py-3">
                    <SkuSubTable spu={s} onMsg={onMsg} />
                  </DenseTableCell>
                </DenseTableRow>
              )}
            </Fragment>
          ))}
        </DenseTableBody>
      </DenseTable>
      {editSpu && (
        <SpuEditDialog
          spu={editSpu}
          onMsg={onMsg}
          onClose={() => {
            setEditSpu(null);
            onChanged();
          }}
        />
      )}
    </div>
  );
}
