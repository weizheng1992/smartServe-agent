import { api } from '@/lib/api';
import { useCallback, useEffect, useMemo, useState } from 'react';

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
  const [mapType, setMapType] = useState('category');
  const [mapValue, setMapValue] = useState('');
  const [staffId, setStaffId] = useState('');
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

  const valueOptions = useMemo(() => (mapType === 'category' ? categories : metrics), [mapType, categories, metrics]);

  const submit = async () => {
    setMsg('');
    const res = await api.ownerMappings.upsert({ mapType, mapValue, staffId });
    setMsg(res.success ? '已登记' : `失败:${'message' in res ? res.message : '未知错误'}`);
    if (res.success) {
      setMapValue('');
      await load();
    }
  };

  const remove = async (row: MappingRow) => {
    setMsg('');
    const res = await api.ownerMappings.remove(row.mapType, row.mapValue);
    setMsg(res.success ? `已撤销:${row.mapValue}` : `失败:${'message' in res ? res.message : '未知错误'}`);
    if (res.success) await load();
  };

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <section className="rounded border border-zinc-200 bg-white p-4 dark:border-zinc-700 dark:bg-zinc-900">
        <h2 className="mb-2 text-sm font-medium">登记 / 改派责任人</h2>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <select
            aria-label="映射类型"
            className="rounded border border-zinc-300 px-2 py-1 dark:border-zinc-600 dark:bg-zinc-800"
            value={mapType}
            onChange={(e) => {
              setMapType(e.target.value);
              setMapValue('');
            }}
          >
            <option value="category">品类</option>
            <option value="metric">指标</option>
          </select>
          <select
            aria-label="维度值"
            className="min-w-48 rounded border border-zinc-300 px-2 py-1 dark:border-zinc-600 dark:bg-zinc-800"
            value={mapValue}
            onChange={(e) => setMapValue(e.target.value)}
          >
            <option value="">— 选择{MAP_TYPE_LABEL[mapType] ?? mapType} —</option>
            {valueOptions.map((opt) => {
              const value = typeof opt === 'string' ? opt : opt.key;
              const label = typeof opt === 'string' ? opt : `${opt.label}(${opt.key})`;
              return (
                <option key={value} value={value}>
                  {label}
                </option>
              );
            })}
          </select>
          <select
            aria-label="负责人"
            className="min-w-40 rounded border border-zinc-300 px-2 py-1 dark:border-zinc-600 dark:bg-zinc-800"
            value={staffId}
            onChange={(e) => setStaffId(e.target.value)}
          >
            <option value="">— 选择负责人 —</option>
            {staff
              .filter((s) => s.status === 'enabled')
              .map((s) => (
                <option key={s.id} value={s.id}>
                  {s.displayName}
                  {s.dept ? `(${s.dept}${s.level ? `·${s.level}` : ''})` : ''}
                </option>
              ))}
          </select>
          <button
            type="button"
            className="rounded bg-zinc-800 px-3 py-1 text-white disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900"
            disabled={!mapValue || !staffId}
            onClick={() => void submit()}
          >
            登记
          </button>
        </div>
        {msg && <div className="mt-2 text-[11px] text-zinc-500">{msg}</div>}
      </section>

      <section className="rounded border border-zinc-200 bg-white p-4 dark:border-zinc-700 dark:bg-zinc-900">
        <h2 className="mb-2 text-sm font-medium">已登记映射({mappings.length})</h2>
        <table className="w-full text-left text-xs">
          <thead className="text-zinc-500">
            <tr>
              <th className="py-1 pr-3">类型</th>
              <th className="py-1 pr-3">维度值</th>
              <th className="py-1 pr-3">负责人</th>
              <th className="py-1 pr-3">状态</th>
              <th className="py-1" />
            </tr>
          </thead>
          <tbody>
            {mappings.map((row) => (
              <tr key={`${row.mapType}:${row.mapValue}`} className="border-t border-zinc-100 dark:border-zinc-800">
                <td className="py-1 pr-3">{MAP_TYPE_LABEL[row.mapType] ?? row.mapType}</td>
                <td className="py-1 pr-3">{row.mapValue}</td>
                <td className="py-1 pr-3">
                  {row.displayName ?? row.staffId}
                  {row.dept ? `(${row.dept}${row.level ? `·${row.level}` : ''})` : ''}
                </td>
                <td className="py-1 pr-3">
                  {row.enabled ? (
                    <span className="text-emerald-600">在职</span>
                  ) : (
                    <span className="text-amber-600">已停用</span>
                  )}
                </td>
                <td className="py-1 text-right">
                  <button type="button" className="text-red-600 hover:underline" onClick={() => void remove(row)}>
                    撤销
                  </button>
                </td>
              </tr>
            ))}
            {mappings.length === 0 && (
              <tr>
                <td colSpan={5} className="py-3 text-center text-zinc-400">
                  暂无登记
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
