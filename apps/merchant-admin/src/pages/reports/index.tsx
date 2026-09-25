import { ResultCard } from '@/components/ResultCard';
import { api } from '@/lib/api';
import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';

type ReportRow = { id: string; title: string; timeWindow: string; createdAt: string | null };
type Section = {
  metric: string;
  unit: string;
  caliber: string;
  chart: string | undefined;
  rows: Record<string, unknown>[];
  cards: any[];
};

/** 我的报告(T4 补强):清单 + 图表重放 —— 存档行数据按图型重绘,CSV 照常导出。 */
export default function ReportsPage() {
  const [reports, setReports] = useState<ReportRow[]>([]);
  const [msg, setMsg] = useState('');
  const [openId, setOpenId] = useState<string | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      setReports((await api.reports.list()).reports || []);
    } catch (err) {
      setMsg(String(err));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function toggleExpand(id: string) {
    if (openId === id) {
      setOpenId(null);
      return;
    }
    setLoading(true);
    try {
      const detail = await api.reports.detail(id);
      const built: Section[] = Object.entries(detail.rows || {}).map(([metric, rows]) => {
        const list = Array.isArray(rows) ? rows : [];
        const cols = list[0] ? Object.keys(list[0]) : [];
        const chart = detail.chart || (metric.endsWith('_trend') ? 'line' : undefined);
        return {
          metric,
          unit: '',
          caliber: '',
          rows: list,
          chart,
          title: detail.title,
          cards: [
            {
              type: 'table',
              title: detail.title,
              columns: cols.map((k) => ({ key: k, label: k })),
              rows: list,
              caliber: '',
            },
          ],
        };
      });
      setSections(built);
      setOpenId(id);
    } catch (err) {
      setMsg(String(err));
    }
    setLoading(false);
  }

  function downloadCsv(id: string) {
    void api.reports.csv(id).then((j) => {
      const blob = new Blob([j.csv], { type: 'text/csv;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = j.filename;
      a.click();
    });
  }

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">我的报告</div>
          <div className="mt-0.5 text-[11px] text-zinc-400">展开可重放图表(存档快照);CSV 随时可导</div>
        </div>
        <Button size="sm" variant="outline" onClick={() => void api.reports.create().then(load)}>
          ＋ 生成报告
        </Button>
      </div>

      {reports.length === 0 && (
        <div className="rounded-xl border border-dashed border-zinc-300 px-4 py-10 text-center text-xs text-zinc-400">
          {msg || '暂无报告 —— 对话里点「存为报告」或右上角生成'}
        </div>
      )}

      <div className="space-y-3">
        {reports.map((r) => (
          <div key={r.id} className="rounded-2xl border border-zinc-200 bg-white">
            <div className="flex items-center justify-between px-4 py-3">
              <div>
                <div className="text-sm">{r.title}</div>
                <div className="mt-0.5 text-[11px] text-zinc-400">
                  {r.createdAt || ''} · {r.timeWindow?.includes('agent_result') ? '来自对话结果' : r.timeWindow}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="ghost" onClick={() => void toggleExpand(r.id)}>
                  {openId === r.id ? '收起' : '展开图表'}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => downloadCsv(r.id)}>
                  下载 CSV
                </Button>
              </div>
            </div>
            {openId === r.id && (
              <div className="space-y-3 border-t border-zinc-100 px-4 py-3">
                {loading && <div className="text-xs text-zinc-400">载入中…</div>}
                {sections.map((sec, i) => (
                  <ResultCard key={i} data={sec} />
                ))}
                {!loading && sections.length === 0 && (
                  <div className="text-xs text-zinc-400">该报告无可重放的数据节</div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
