// 数据问答结果卡(T4 从 FloatingAgent 抽出复用:对话面板与常驻看板同形渲染)
// 入参形状 = lib/analytics-frames.AskFrameData(F4:data:any 换形状契约)
import { BarChart } from '@/components/BarChart';
import { LineChart } from '@/components/LineChart';
import { type AskCardColumn, type AskFrameData, type AskRow, type AskTrust } from '@/lib/analytics-frames';

// 明确不做条形图的指标:逐笔列表/窗口列不是排行语义,画条会误导
const NO_BAR_METRICS = new Set(['order_overview', 'customer_orders']);

// 信任章(ADR-0010):机器语义字段;verified 为默认态零视觉噪音,
// composed/explored 才显章 —— 商户要能一眼分辨「这个数字敢不敢直接信」
const TRUST_LABELS: Record<AskTrust, string> = {
  verified: '核验口径',
  composed: '组合查询',
  explored: '探索性结果',
};

function TrustBadge({ trust }: { trust?: AskTrust }) {
  if (!trust || trust === 'verified') return null;
  const style =
    trust === 'explored' ? 'border-amber-200 bg-amber-50 text-amber-600' : 'border-sky-200 bg-sky-50 text-sky-600';
  return (
    <span className={`ml-2 rounded border px-1 py-0.5 align-middle text-[10px] ${style}`}>
      {TRUST_LABELS[trust] ?? trust}
    </span>
  );
}

// 生成 SQL 折叠(explored 帧必带):探索通道的口径可审计承诺 —— 数字哪来的,
// 展开即查;默认收起不打扰
function GeneratedSqlFold({ sql }: { sql?: string }) {
  if (!sql) return null;
  return (
    <details className="border-t border-zinc-100 px-3 py-1.5 text-[11px] text-zinc-400">
      <summary className="cursor-pointer select-none">查看生成 SQL(探索性查询,非核验口径)</summary>
      <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-all text-[10px] leading-4 text-zinc-500">
        {sql}
      </pre>
    </details>
  );
}

// B2 归因叙事(ADR-0011):与数据列视觉分离的独立区块 + 「AI 推断(非数据)」
// 章 —— 因果叙述允许,但必须让商户一眼知道「这句是推断,上面表格才是数据」
function NarrativeBlock({ narrative }: { narrative?: { text: string } }) {
  if (!narrative?.text) return null;
  return (
    <div className="border-t border-amber-100 bg-amber-50/60 px-3 py-2 text-[11px] leading-4 text-zinc-600">
      <span className="mr-1 rounded border border-amber-300 bg-amber-50 px-1 py-0.5 text-[10px] text-amber-700">
        AI 推断(非数据)
      </span>
      {narrative.text}
    </div>
  );
}

// 单元格诚实呈现:缺值渲染「—」,不出 "null"/"undefined" 字面量(同页金额
// 口径 toFixed(2)+「—」同律,夜审 2026-09-29 收口)
function cellText(v: unknown): string {
  return v === null || v === undefined || v === '' ? '—' : String(v);
}

// 折线取行内第 2 列为值;列缺位或非数值(如对比卡第 2 列是「品类」文案)一律
// 不是可绘制数列 —— 诚实降级表格,绝不画 NaN 图(实弹:历史持久化帧重放)
function linePoints(rows: AskRow[]): Array<{ label: string; value: number }> | null {
  const points = rows.map((r: AskRow) => {
    const vals = Object.values(r);
    return { label: String(vals[0] ?? ''), value: Number(vals[1]) };
  });
  if (!points.length || points.some((p) => !Number.isFinite(p.value))) return null;
  return points;
}

export function rankingPoints(data: AskFrameData): Array<{ label: string; value: number }> | null {
  const rows: AskRow[] = Array.isArray(data.rows) ? data.rows : [];
  if (rows.length < 2 || NO_BAR_METRICS.has(data.metric ?? '')) return null;
  const cols = Object.keys(rows[0] || {});
  if (!cols.length) return null;
  const labelCol = cols[0];
  const valueCol = cols[cols.length - 1];
  const points = rows
    .map((r: AskRow) => ({ label: String(r[labelCol] ?? ''), value: Number(r[valueCol]) }))
    .filter((p: { label: string; value: number }) => Number.isFinite(p.value));
  if (points.length < 2) return null;
  return points.slice(0, 10);
}

// 注:本组件内 3 张原生 <table> 为【豁免】—— shadcn 迁移裁决(2026-10-09):
// ① 四处共用渲染缝(悬浮面板/analytics 全屏/看板/报告),改密度会同时改四个载体;
// ② 卡片内 px-3 py-1.5 / 12px 是容器受限下的刻意紧凑;
// ③ ResultCard.test 钉死 div.overflow-x-auto 滚动包裹(ui Table 包裹层类名不同)。
// 如需迁移须连测试与四处载体冒烟一起做,勿单独替换标签。
export function ResultCard({ data }: { data: AskFrameData }) {
  if (data.chart === 'line' && Array.isArray(data.rows) && data.rows.length < 2) {
    // 用户点名折线但数据点不足:诚实说明,表格呈现(不静默降级)
    return (
      <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
        <div className="border-b border-zinc-100 px-3 py-2 text-xs font-medium text-zinc-500">
          {data.title || `${data.metric} · ${data.unit}`}
          <TrustBadge trust={data.trust} />
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
          <TrustBadge trust={data.trust} />
        </div>
        <LineChart points={points} unit={data.unit} />
        {data.caliber ? (
          <div className="border-t border-zinc-100 px-3 py-1.5 text-[11px] text-zinc-400">口径:{data.caliber}</div>
        ) : null}
        <GeneratedSqlFold sql={data.generatedSql} />
        <NarrativeBlock narrative={data.narrative} />
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
        <TrustBadge trust={data.trust} />
        <div className="px-3 py-2 text-[11px] text-zinc-400">
          该结果不是排行形状(需 ≥2 行数值),无法绘制条形图 —— 已按表格诚实呈现。
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="border-b border-zinc-100 text-left text-zinc-400">
                {card.columns.map((c: AskCardColumn) => (
                  <th key={c.key} className="px-3 py-1.5 font-medium">
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {card.rows.map((r: AskRow, i: number) => (
                /* biome-ignore lint/suspicious/noArrayIndexKey: 通用结果表行无稳定业务主键,按序静态渲染 */
                <tr key={i} className="border-b border-zinc-50">
                  {card.columns.map((c: AskCardColumn) => (
                    <td key={c.key} className="px-3 py-1.5">
                      {cellText(r[c.key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="border-t border-zinc-100 px-3 py-1.5 text-[11px] text-zinc-400">口径:{card.caliber}</div>
        <GeneratedSqlFold sql={data.generatedSql} />
        <NarrativeBlock narrative={data.narrative} />
      </div>
    );
  }
  const header = data.title || card.title;
  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
      <div className="border-b border-zinc-100 px-3 py-2 text-xs font-medium text-zinc-500">{header}</div>
      <TrustBadge trust={data.trust} />
      {bars ? <BarChart points={bars} unit={data.unit} /> : null}
      {/* 宽表(UUID 列/多列卡)在面板窄容器里必须可左右滚,卡片根 overflow-hidden 不裁数据 */}
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-zinc-100 text-left text-zinc-400">
              {card.columns.map((c: AskCardColumn) => (
                <th key={c.key} className="px-3 py-1.5 font-medium">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {card.rows.map((r: AskRow, i: number) => (
              /* biome-ignore lint/suspicious/noArrayIndexKey: 通用结果表行无稳定业务主键,按序静态渲染 */
              <tr key={i} className="border-b border-zinc-50">
                {card.columns.map((c: AskCardColumn) => (
                  <td key={c.key} className="px-3 py-1.5">
                    {cellText(r[c.key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="border-t border-zinc-100 px-3 py-1.5 text-[11px] text-zinc-400">口径:{card.caliber}</div>
      <GeneratedSqlFold sql={data.generatedSql} />
      <NarrativeBlock narrative={data.narrative} />
    </div>
  );
}

function ResultTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (!rows.length) return null;
  const cols = Object.keys(rows[0]);
  return (
    <div className="overflow-x-auto">
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
                  {cellText(r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
