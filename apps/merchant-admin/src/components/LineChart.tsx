// 零依赖 SVG 折线图(时间序列卡;ECharts 接入前先用同形渲染,接口一致)
export interface LinePoint {
  label: string;
  value: number;
}

export function LineChart({ points, unit }: { points: LinePoint[]; unit?: string }) {
  if (points.length < 2) {
    return <div className="p-3 text-xs text-zinc-400">数据点不足,无法绘制折线(诚实空)</div>;
  }
  const w = 640;
  const h = 180;
  const pad = { l: 44, r: 12, t: 12, b: 24 };
  const values = points.map((p) => p.value);
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const span = max - min || 1;
  const x = (i: number) => pad.l + (i * (w - pad.l - pad.r)) / (points.length - 1);
  const y = (v: number) => pad.t + (1 - (v - min) / span) * (h - pad.t - pad.b);
  const line = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ');
  const area = `${line} L${x(points.length - 1).toFixed(1)},${h - pad.b} L${pad.l},${h - pad.b} Z`;
  const gridVals = [min, min + span / 2, max];
  const labelEvery = Math.ceil(points.length / 8);

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" role="img" aria-label="趋势折线图">
      {gridVals.map((v, i) => (
        /* biome-ignore lint/suspicious/noArrayIndexKey: SVG 网格线/数据点图元按序静态渲染,无业务身份 */
        <g key={i}>
          <line x1={pad.l} x2={w - pad.r} y1={y(v)} y2={y(v)} stroke="#f4f4f5" />
          <text x={4} y={y(v) + 3} fontSize="9" fill="#a1a1aa">
            {Math.round(v).toLocaleString()}
          </text>
        </g>
      ))}
      <path d={area} fill="rgba(24,24,27,0.06)" />
      <path d={line} fill="none" stroke="#18181b" strokeWidth="2" />
      {points.map((p, i) => (
        /* biome-ignore lint/suspicious/noArrayIndexKey: SVG 网格线/数据点图元按序静态渲染,无业务身份 */
        <g key={`pt-${i}`}>
          {/* 透明大热区 + 实心小点:悬停出浏览器原生气泡(数值即看即读) */}
          <circle cx={x(i)} cy={y(p.value)} r={8} fill="transparent">
            <title>{`${p.label} · ${p.value.toLocaleString()}${unit || ''}`}</title>
          </circle>
          <circle cx={x(i)} cy={y(p.value)} r={2.5} fill="#18181b" />
        </g>
      ))}
      {points.map((p, i) =>
        i % labelEvery === 0 ? (
          /* biome-ignore lint/suspicious/noArrayIndexKey: SVG 网格线/数据点图元按序静态渲染,无业务身份 */
          <text key={i} x={x(i)} y={h - 8} fontSize="9" fill="#a1a1aa" textAnchor="middle">
            {p.label}
          </text>
        ) : null,
      )}
      <title>{`趋势(${unit || ''}):最低 ${Math.min(...values).toLocaleString()} · 最高 ${max.toLocaleString()}`}</title>
    </svg>
  );
}
