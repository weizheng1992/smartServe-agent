import { useCallback, useEffect, useState } from 'react';
import { Button } from 'ui';
import { api } from '@/lib/api';

export default function ReportsPage() {
  const [reports, setReports] = useState<Array<{ id: string; title: string; timeWindow: string; createdAt: string | null }>>([]);
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    try { setReports((await api.reports.list()).reports || []); } catch (err) { setMsg(String(err)); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="mx-auto max-w-3xl rounded-xl border border-zinc-200 bg-white">
      <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3">
        <span className="text-sm font-medium">我的报告</span>
        <Button size="sm" variant="outline" onClick={() => void api.reports.create().then(load)}>＋ 生成报告</Button>
      </div>
      <div className="divide-y divide-zinc-50">
        {reports.length === 0 && <div className="px-4 py-6 text-xs text-zinc-400">{msg || '暂无报告(点右上生成)'}</div>}
        {reports.map((r) => (
          <div key={r.id} className="flex items-center justify-between px-4 py-3">
            <div>
              <div className="text-sm">{r.title}</div>
              <div className="mt-0.5 text-[11px] text-zinc-400">{r.createdAt || ''} · {r.timeWindow}</div>
            </div>
            <Button size="sm" variant="ghost" onClick={() => {
              void api.reports.csv(r.id).then((j) => {
                const blob = new Blob([j.csv], { type: 'text/csv' });
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = j.filename;
                a.click();
              });
            }}>
              下载 CSV
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}
