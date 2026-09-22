// 零依赖横向条形图(排行卡;与 LineChart 同形渲染,接口一致)
export interface BarPoint {
  label: string;
  value: number;
}

export function BarChart({ points, unit }: { points: BarPoint[]; unit?: string }) {
  if (points.length < 2) {
    return <div className="p-3 text-xs text-zinc-400">数据点不足,无法绘制条形图(诚实空)</div>;
  }
  const max = Math.max(...points.map((p) => p.value), 1);
  return (
    <div className="space-y-1.5 px-3 py-2" role="img" aria-label="排行条形图">
      {points.map((p, i) => (
        <div key={i} className="flex items-center gap-2">
          <div className="w-[38%] truncate text-right text-[11px] text-zinc-500" title={p.label}>
            {p.label}
          </div>
          <div className="h-3.5 flex-1 overflow-hidden rounded bg-zinc-100">
            <div className="h-full rounded bg-zinc-800" style={{ width: `${Math.max((p.value / max) * 100, 2)}%` }} />
          </div>
          <div className="w-16 shrink-0 text-right text-[11px] tabular-nums text-zinc-700">
            {p.value.toLocaleString()}
          </div>
        </div>
      ))}
      {unit ? <div className="pt-0.5 text-right text-[10px] text-zinc-400">单位:{unit}</div> : null}
    </div>
  );
}
