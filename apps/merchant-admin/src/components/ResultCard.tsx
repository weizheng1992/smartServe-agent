// 数据问答结果卡(T4 从 FloatingAgent 抽出复用:对话面板与常驻看板同形渲染)
import { BarChart } from '@/components/BarChart';
import { LineChart } from '@/components/LineChart';

// 明确不做条形图的指标:逐笔列表/窗口列不是排行语义,画条会误导
const NO_BAR_METRICS = new Set(['order_overview', 'customer_orders']);

// 折线取行内第 2 列为值;列缺位或非数值(如对比卡第 2 列是「品类」文案)一律
// 不是可绘制数列 —— 诚实降级表格,绝不画 NaN 图(实弹:历史持久化帧重放)
function linePoints(rows: any[]): Array<{ label: string; value: number }> | null {
  const points = rows.map((r: any) => {
    const vals = Object.values(r);
    return { label: String(vals[0] ?? ''), value: Number(vals[1]) };
  });
  if (!points.length || points.some((p) => !Number.isFinite(p.value))) return null;
  return points;
}

export function rankingPoints(data: any): Array<{ label: string; value: number }> | null {
  const rows: any[] = Array.isArray(data.rows) ? data.rows : [];
  if (rows.length < 2 || NO_BAR_METRICS.has(data.metric)) return null;
  const cols = Object.keys(rows[0] || {});
  if (!cols.length) return null;
  const labelCol = cols[0];
  const valueCol = cols[cols.length - 1];
  const points = rows
    .map((r: any) => ({ label: String(r[labelCol] ?? ''), value: Number(r[valueCol]) }))
    .filter((p: { label: string; value: number }) => Number.isFinite(p.value));
  if (points.length < 2) return null;
  return points.slice(0, 10);
}

export function ResultCard({ data }: { data: any }) {
  if (data.chart === 'line' && Array.isArray(data.rows) && data.rows.length < 2) {
    // 用户点名折线但数据点不足:诚实说明,表格呈现(不静默降级)
    return (
      <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
        <div className="border-b border-zinc-100 px-3 py-2 text-xs font-medium text-zinc-500">
          {data.title || `${data.metric} · ${data.unit}`}
        </div>
        <div className="px-3 py-2 text-[11px] text-zinc-400">
          折线至少需要 2 个数据点,当前结果不满足 —— 按表格呈现(诚实降级,未绘制空图)。
        </div>
        <ResultTable rows={data.rows || []} />
      </div>
    );
  }
  if (data.chart === 'line' && Array.isArray(data.rows) && data.rows.length >= 2) {
    const points = linePoints(data.rows);
    if (!points) {
      // 点位齐但值列非数值:该结果不是数值数列(如商品对比卡),折线无意义
      return (
        <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
          <div className="border-b border-zinc-100 px-3 py-2 text-xs font-medium text-zinc-500">
            {data.title || `${data.metric} · ${data.unit}`}
          </div>
          <div className="px-3 py-2 text-[11px] text-zinc-400">
            该结果不是数值数列,折线图不适用 —— 按表格呈现(诚实降级,未绘制空图)。
          </div>
          <ResultTable rows={data.rows || []} />
        </div>
      );
    }
    return (
      <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
        <div className="border-b border-zinc-100 px-3 py-2 text-xs font-medium text-zinc-500">
          {data.title || `${data.metric} · ${data.unit}`}
        </div>
        <LineChart points={points} unit={data.unit} />
        {data.caliber ? (
          <div className="border-t border-zinc-100 px-3 py-1.5 text-[11px] text-zinc-400">口径:{data.caliber}</div>
        ) : null}
      </div>
    );
  }
  const card = (data.cards || [])[0];
  if (!card) return <div className="text-sm">{data.message || '空结果'}</div>;
  if (card.type !== 'table') return <div className="text-sm">{card.text}</div>;
  // 图型优先级:用户指令(table=只表格 / bar=强制条形)→ 缺省按排行形状自动
  const bars = data.chart === 'table' ? null : rankingPoints(data);
  if (data.chart === 'bar' && !bars && Array.isArray(data.rows) && data.rows.length >= 2) {
    return (
      <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
        <div className="border-b border-zinc-100 px-3 py-2 text-xs font-medium text-zinc-500">{card.title}</div>
        <div className="px-3 py-2 text-[11px] text-zinc-400">
          该结果不是排行形状(需 ≥2 行数值),无法绘制条形图 —— 已按表格诚实呈现。
        </div>
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-zinc-100 text-left text-zinc-400">
              {card.columns.map((c: any) => (
                <th key={c.key} className="px-3 py-1.5 font-medium">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {card.rows.map((r: any, i: number) => (
              /* biome-ignore lint/suspicious/noArrayIndexKey: 通用结果表行无稳定业务主键,按序静态渲染 */
              <tr key={i} className="border-b border-zinc-50">
                {card.columns.map((c: any) => (
                  <td key={c.key} className="px-3 py-1.5">
                    {String(r[c.key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <div className="border-t border-zinc-100 px-3 py-1.5 text-[11px] text-zinc-400">口径:{card.caliber}</div>
      </div>
    );
  }
  const header = data.title || card.title;
  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
      <div className="border-b border-zinc-100 px-3 py-2 text-xs font-medium text-zinc-500">{header}</div>
      {bars ? <BarChart points={bars} unit={data.unit} /> : null}
      <table className="w-full text-[12px]">
        <thead>
          <tr className="border-b border-zinc-100 text-left text-zinc-400">
            {card.columns.map((c: any) => (
              <th key={c.key} className="px-3 py-1.5 font-medium">
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {card.rows.map((r: any, i: number) => (
            /* biome-ignore lint/suspicious/noArrayIndexKey: 通用结果表行无稳定业务主键,按序静态渲染 */
            <tr key={i} className="border-b border-zinc-50">
              {card.columns.map((c: any) => (
                <td key={c.key} className="px-3 py-1.5">
                  {String(r[c.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="border-t border-zinc-100 px-3 py-1.5 text-[11px] text-zinc-400">口径:{card.caliber}</div>
    </div>
  );
}

function ResultTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows.length) return null;
  const cols = Object.keys(rows[0]);
  return (
    <table className="w-full text-[12px]">
      <thead>
        <tr className="border-b border-zinc-100 text-left text-zinc-400">
          {cols.map((c) => (
            <th key={c} className="px-3 py-1.5 font-medium">
              {c}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          /* biome-ignore lint/suspicious/noArrayIndexKey: 通用结果表行无稳定业务主键,按序静态渲染 */
          <tr key={i} className="border-b border-zinc-50">
            {cols.map((c) => (
              <td key={c} className="px-3 py-1.5">
                {String(r[c])}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
