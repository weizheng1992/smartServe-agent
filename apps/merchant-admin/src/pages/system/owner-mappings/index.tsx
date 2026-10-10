import {
  DenseTable,
  DenseTableBody,
  DenseTableCell,
  DenseTableHead,
  DenseTableHeader,
  DenseTableRow,
} from '@/components/dense-table';
import { api } from '@/lib/api';
import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';
import { OwnerMappingDialog } from './owner-mapping-dialog';

type MappingRow = {
  mapType: string;
  mapValue: string;
  staffId: string;
  ownerType: string;
  updatedAt: string;
  displayName: string | null;
  dept: string | null;
  level: string | null;
  enabled: boolean;
};

type StaffOption = { id: string; displayName: string; dept: string | null; level: string | null; status: string };

const MAP_TYPE_LABEL: Record<string, string> = { category: '品类', metric: '指标' };

// 「该找谁」责任人维护(spec .scratch/owner-routing §5):品类/指标 → 员工映射。
// 下拉吃语义注册表闭集(服务端 GET 同载,前端零硬编码);PUT/DELETE 仅老板/管理员
// (闸在服务端,前端按 400/403 文案如实呈现)。商品/活动所有权随实体行编辑,不在此页。
export default function OwnerMappingsPage() {
  const [mappings, setMappings] = useState<MappingRow[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [metrics, setMetrics] = useState<Array<{ key: string; label: string }>>([]);
  const [staff, setStaff] = useState<StaffOption[]>([]);
  const [creating, setCreating] = useState(false);
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    const [list, staffRes] = await Promise.all([api.ownerMappings.list(), api.staff.list()]);
    setMappings(list.mappings || []);
    setCategories(list.categories || []);
    setMetrics(list.metrics || []);
    setStaff((staffRes.staff || []) as StaffOption[]);
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const remove = async (row: MappingRow) => {
    setMsg('');
    const res = await api.ownerMappings.remove(row.mapType, row.mapValue);
    setMsg(res.success ? `已撤销:${row.mapValue}` : `失败:${'message' in res ? res.message : '未知错误'}`);
    if (res.success) await load();
  };

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <section className="rounded border border-zinc-200 bg-white p-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-medium">已登记映射({mappings.length})</h2>
          <Button size="sm" onClick={() => setCreating(true)}>
            + 登记 / 改派
          </Button>
        </div>
        <DenseTable className="text-left text-xs">
          <DenseTableHeader>
            <DenseTableRow className="hover:bg-transparent">
              <DenseTableHead className="py-1 pr-3 text-xs">类型</DenseTableHead>
              <DenseTableHead className="py-1 pr-3 text-xs">维度值</DenseTableHead>
              <DenseTableHead className="py-1 pr-3 text-xs">负责人</DenseTableHead>
              <DenseTableHead className="py-1 pr-3 text-xs">状态</DenseTableHead>
              <DenseTableHead className="py-1 text-xs" />
            </DenseTableRow>
          </DenseTableHeader>
          <DenseTableBody>
            {mappings.map((row) => (
              <DenseTableRow key={`${row.mapType}:${row.mapValue}`} className="border-t border-zinc-100">
                <DenseTableCell className="py-1 pr-3 text-xs">
                  {MAP_TYPE_LABEL[row.mapType] ?? row.mapType}
                </DenseTableCell>
                <DenseTableCell className="py-1 pr-3 text-xs">{row.mapValue}</DenseTableCell>
                <DenseTableCell className="py-1 pr-3 text-xs">
                  {row.displayName ?? row.staffId}
                  {row.dept ? `(${row.dept}${row.level ? `·${row.level}` : ''})` : ''}
                </DenseTableCell>
                <DenseTableCell className="py-1 pr-3 text-xs">
                  {row.enabled ? (
                    <span className="text-emerald-600">在职</span>
                  ) : (
                    <span className="text-amber-600">已停用</span>
                  )}
                </DenseTableCell>
                <DenseTableCell className="py-1 text-right text-xs">
                  <Button
                    type="button"
                    variant="link"
                    className="h-auto cursor-pointer p-0 text-xs text-red-600 hover:text-red-600 hover:underline"
                    onClick={() => void remove(row)}
                  >
                    撤销
                  </Button>
                </DenseTableCell>
              </DenseTableRow>
            ))}
            {mappings.length === 0 && (
              <DenseTableRow>
                <DenseTableCell colSpan={5} className="py-3 text-center text-zinc-400">
                  暂无登记
                </DenseTableCell>
              </DenseTableRow>
            )}
          </DenseTableBody>
        </DenseTable>
      </section>

      {creating && (
        <OwnerMappingDialog
          categories={categories}
          metrics={metrics}
          staff={staff}
          onSaved={setMsg}
          onClose={() => {
            setCreating(false);
            void load();
          }}
        />
      )}
      {msg && <div className="text-[11px] text-zinc-500">{msg}</div>}
    </div>
  );
}
