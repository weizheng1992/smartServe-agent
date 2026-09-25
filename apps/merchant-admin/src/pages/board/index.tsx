// 常驻数据看板(T4;wayfinder dynamic-analytics Q5/Q6)。
// 钉卡 = 保存「问句 + 上下文」而非查询结果;看板按卡片重放 /ask 定时刷新 ——
// 权限/闭集/口径全复用对话管线,零新后端,不碰 SQL(08-D1 同源纪律)。
// 刷新策略:60s 轮询 + 页面不可见时暂停 + 手动立即刷新。

import { ResultCard } from '@/components/ResultCard';
import { api } from '@/lib/api';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { Button } from 'ui';

type Pin = { id: string; question: string; route: string; pinnedAt: string };
type ReplayState = { frames: any[] | null; error: string | null; at: string | null };

const REFRESH_MS = 60_000;

function loadPins(): Pin[] {
  try {
    return JSON.parse(localStorage.getItem('merchant-admin.board') || '[]');
  } catch {
    return [];
  }
}

function sessionId(): string {
  let sid = localStorage.getItem('merchant-admin.session');
  if (!sid) {
    sid = `s-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    localStorage.setItem('merchant-admin.session', sid);
  }
  return sid;
}

export default function BoardPage() {
  const navigate = useNavigate();
  const [pins, setPins] = useState<Pin[]>(loadPins);
  const [states, setStates] = useState<Record<string, ReplayState>>({});
  const [refreshing, setRefreshing] = useState(false);
  const timer = useRef<number | null>(null);

  const replay = useCallback(async (list: Pin[]) => {
    setRefreshing(true);
    const sid = sessionId();
    await Promise.all(
      list.map(async (pin) => {
        try {
          const frames = await api.ask(pin.question, { route: pin.route, selection: [], sessionId: sid });
          setStates((prev) => ({ ...prev, [pin.id]: { frames, error: null, at: new Date().toLocaleTimeString() } }));
        } catch (err) {
          setStates((prev) => ({
            ...prev,
            [pin.id]: { frames: null, error: String(err), at: new Date().toLocaleTimeString() },
          }));
        }
      }),
    );
    setRefreshing(false);
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: 挂载时只 replay 一次,轮询走 loadPins()
  useEffect(() => {
    void replay(pins);
    timer.current = window.setInterval(() => {
      if (!document.hidden) void replay(loadPins());
    }, REFRESH_MS);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, []);

  // 大屏模式:浏览器全屏 + 网格铺开(看板挂壁/投屏场景)
  const [bigScreen, setBigScreen] = useState(false);
  useEffect(() => {
    const onFs = () => setBigScreen(Boolean(document.fullscreenElement));
    document.addEventListener('fullscreenchange', onFs);
    return () => document.removeEventListener('fullscreenchange', onFs);
  }, []);
  function toggleBigScreen() {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void document.documentElement.requestFullscreen().catch(() => {});
  }

  function removePin(id: string) {
    const next = loadPins().filter((p) => p.id !== id);
    localStorage.setItem('merchant-admin.board', JSON.stringify(next));
    setPins(next);
  }

  return (
    <div className={bigScreen ? 'min-h-screen bg-zinc-50 p-6' : 'mx-auto max-w-4xl'}>
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">数据看板</div>
          <div className="mt-0.5 text-[11px] text-zinc-400">
            钉住的问句每 {REFRESH_MS / 1000}s 自动重放刷新(页面不可见时暂停);数据现查,口径不过期
          </div>
        </div>
        <div className="flex items-center gap-2">
          {refreshing && <span className="text-[11px] text-zinc-400">刷新中…</span>}
          <Button size="sm" variant="outline" onClick={() => void replay(loadPins())}>
            立即刷新
          </Button>
          <Button size="sm" variant="outline" onClick={toggleBigScreen}>
            {bigScreen ? '退出大屏' : '⛶ 大屏'}
          </Button>
        </div>
      </div>

      {pins.length === 0 && (
        <div className="rounded-xl border border-dashed border-zinc-300 px-4 py-10 text-center text-xs text-zinc-400">
          还没有钉卡 —— 在任意页面的数据分析助手里点结果卡下方的「📌 钉看板」
        </div>
      )}

      <div className={bigScreen ? 'grid grid-cols-2 gap-4 xl:grid-cols-3' : 'space-y-4'}>
        {pins.map((pin) => {
          const st = states[pin.id] || { frames: null, error: null, at: null };
          const results = (st.frames || []).filter((f) => f.event === 'result');
          const failed = (st.frames || []).find((f) => f.event === 'unsupported' || f.event === 'error');
          return (
            <div key={pin.id} className="rounded-2xl border border-zinc-200 bg-white p-3">
              <div className="mb-2 flex items-center justify-between">
                <div className="text-sm font-medium">{pin.question}</div>
                <div className="flex items-center gap-2 text-[11px] text-zinc-400">
                  {st.at && <span>刷新于 {st.at}</span>}
                  <button type="button" className="hover:text-zinc-900" onClick={() => removePin(pin.id)}>
                    移除
                  </button>
                </div>
              </div>
              {st.error && <div className="text-xs text-red-500">刷新失败:{st.error}</div>}
              {!st.error && failed && (
                <div className="text-xs text-zinc-500">{failed.data?.message || failed.event}</div>
              )}
              {results.map((f: any, i: number) => (
                /* biome-ignore lint/suspicious/noArrayIndexKey: SseFrame 无业务 id,看板只读重放不重排 */
                <div key={i} className="mb-2">
                  <ResultCard data={f.data} />
                  {f.data.summary ? (
                    <div className="mt-1 text-[11px] leading-relaxed text-zinc-500">
                      <span className="mr-1 rounded bg-zinc-100 px-1 py-0.5 text-[10px] text-zinc-500">速览</span>
                      {f.data.summary}
                    </div>
                  ) : null}
                </div>
              ))}
              {!st.error && !results.length && !failed && st.frames && (
                <div className="text-xs text-zinc-400">本轮无结果(诚实空)</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
