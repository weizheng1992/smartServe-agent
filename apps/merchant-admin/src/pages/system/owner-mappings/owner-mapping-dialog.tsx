import { FormDialogShell } from '@/components/form-dialog-shell';
import { SearchableSelect } from '@/components/searchable-select';
import { api, errMsgOf } from '@/lib/api';
import { useState } from 'react';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from 'ui';
import { MAP_TYPE_LABEL } from './map-type-label';

type StaffOption = { id: string; displayName: string; dept: string | null; level: string | null; status: string };

interface Props {
  categories: string[];
  metrics: Array<{ key: string; label: string }>;
  staff: StaffOption[];
  /** props 命名收敛:onSaved → onMsg(2026-10-15 候选④)。 */
  onMsg: (msg: string) => void;
  onClose: () => void;
}

/** 登记 / 改派责任人弹窗:维度值下拉吃语义注册表闭集(服务端同载,前端零
 * 硬编码;指标 40+ 项走可搜索);PUT 闸在服务端(仅老板/管理员)。 */
export function OwnerMappingDialog({ categories, metrics, staff, onMsg, onClose }: Props) {
  const [mapType, setMapType] = useState('category');
  const [mapValue, setMapValue] = useState('');
  const [staffId, setStaffId] = useState('');

  const valueOptions = mapType === 'category' ? categories : metrics;

  return (
    <FormDialogShell
      title="登记 / 改派责任人"
      subtitle="「该找谁」路由按此映射解析;同维度值重复登记即改派。仅老板/管理员可写(闸在服务端)。"
      maxWidth="max-w-md"
      submitLabel="登记"
      submitDisabled={!mapValue || !staffId}
      onClose={onClose}
      onSubmit={async () => {
        const res = await api.ownerMappings.upsert({ mapType, mapValue, staffId });
        if (!res.success) return errMsgOf(res);
        onMsg(`已登记:${mapValue}`);
        return null;
      }}
    >
      <div>
        <div className="mb-1.5 font-medium text-zinc-700">映射类型</div>
        <Select
          value={mapType}
          onValueChange={(v) => {
            setMapType(v);
            setMapValue('');
          }}
        >
          <SelectTrigger aria-label="映射类型" className="h-auto w-28 rounded-lg border-zinc-300 px-2 py-1.5">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="category">品类</SelectItem>
            <SelectItem value="metric">指标</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div>
        <div className="mb-1.5 font-medium text-zinc-700">维度值</div>
        <SearchableSelect
          ariaLabel="维度值"
          value={mapValue}
          onValueChange={(v) => setMapValue(v)}
          options={valueOptions.map((opt) => {
            const value = typeof opt === 'string' ? opt : opt.key;
            const label = typeof opt === 'string' ? opt : `${opt.label}(${opt.key})`;
            return { value, label };
          })}
          placeholder={`— 选择${MAP_TYPE_LABEL[mapType] ?? mapType} —`}
          triggerClassName="w-full"
        />
      </div>
      <div>
        <div className="mb-1.5 font-medium text-zinc-700">负责人</div>
        <Select value={staffId} onValueChange={(v) => setStaffId(v)}>
          <SelectTrigger aria-label="负责人" className="h-auto w-full rounded-lg border-zinc-300 px-2 py-1.5">
            <SelectValue placeholder="— 选择负责人 —" />
          </SelectTrigger>
          <SelectContent>
            {staff
              .filter((s) => s.status === 'enabled')
              .map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.displayName}
                  {s.dept ? `(${s.dept}${s.level ? `·${s.level}` : ''})` : ''}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
      </div>
    </FormDialogShell>
  );
}
