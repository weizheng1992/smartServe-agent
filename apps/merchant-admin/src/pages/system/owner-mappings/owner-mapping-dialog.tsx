import { SearchableSelect } from '@/components/searchable-select';
import { api } from '@/lib/api';
import { useState } from 'react';
import {
  Button,
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from 'ui';

type StaffOption = { id: string; displayName: string; dept: string | null; level: string | null; status: string };

interface Props {
  categories: string[];
  metrics: Array<{ key: string; label: string }>;
  staff: StaffOption[];
  onSaved: (msg: string) => void;
  onClose: () => void;
}

const MAP_TYPE_LABEL: Record<string, string> = { category: '品类', metric: '指标' };

/** 登记 / 改派责任人弹窗:维度值下拉吃语义注册表闭集(服务端同载,前端零
 * 硬编码;指标 40+ 项走可搜索);PUT 闸在服务端(仅老板/管理员)。 */
export function OwnerMappingDialog({ categories, metrics, staff, onSaved, onClose }: Props) {
  const [mapType, setMapType] = useState('category');
  const [mapValue, setMapValue] = useState('');
  const [staffId, setStaffId] = useState('');
  const [err, setErr] = useState('');

  const valueOptions = mapType === 'category' ? categories : metrics;

  async function submit() {
    const res = await api.ownerMappings.upsert({ mapType, mapValue, staffId });
    if (res.success) {
      onSaved(`已登记:${mapValue}`);
      onClose();
    } else {
      setErr(`失败:${'message' in res ? res.message : '未知错误'}`);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md rounded-xl border-zinc-200 text-zinc-900 shadow-xl">
        <DialogHeader className="pb-3 border-b border-zinc-100">
          <DialogTitle className="text-base font-bold text-zinc-900">登记 / 改派责任人</DialogTitle>
          <p className="mt-1 text-xs text-zinc-500">
            「该找谁」路由按此映射解析;同维度值重复登记即改派。仅老板/管理员可写(闸在服务端)。
          </p>
        </DialogHeader>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto py-4 text-xs">
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
          {err && <div className="text-[11px] text-red-600">{err}</div>}
        </div>

        <DialogFooter className="gap-2 pt-3 sm:gap-0 border-t border-zinc-100">
          <Button type="button" variant="outline" size="sm" onClick={onClose} className="text-xs cursor-pointer">
            取消
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={!mapValue || !staffId}
            onClick={() => void submit()}
            className="text-xs font-bold cursor-pointer"
          >
            登记
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
