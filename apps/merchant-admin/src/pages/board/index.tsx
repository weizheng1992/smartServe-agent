// 常驻数据看板(T4;wayfinder dynamic-analytics Q5/Q6)。
// 钉卡 = 保存「问句 + 上下文」而非查询结果;看板按卡片重放 /ask 定时刷新 ——
// 权限/闭集/口径全复用对话管线,零新后端,不碰 SQL(08-D1 同源纪律)。
// 刷新策略:60s 轮询 + 页面不可见时暂停 + 手动立即刷新。
// 2026-10-15 起:重放走 lib/ask-session(每 pin 一个会话实例,replace 整轮换帧
// 防闪空);重放不带 sessionId —— 重放非对话,服务端双闸零读零写(多轮记忆
// 不受看板轮询污染);也刻意不接 resume:重放=刷新,要的是新数据,resume 只会
// 取回 600s 内缓存的旧帧。重放与手动刷新互斥(busy 闸,慢流>60s 严禁重叠 ask)。

import { ResultCard } from '@/components/ResultCard';
import { CreditsCard } from '@/components/credits-card';
import type { SessionFrame } from '@/lib/analytics-frames';
import { type AskSession, createAskSession, useAskSession } from '@/lib/ask-session';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from 'ui';

type Pin = { id: string; question: string; route: string; pinnedAt: string };

const REFRESH_MS = 60_000;

function loadPins(): Pin[] {
  try {
    return JSON.parse(localStorage.getItem('merchant-admin.board') || '[]');
  } catch {
    return [];
  }
}

export default function BoardPage() {
  const [pins, setPins] = useState<Pin[]>(loadPins);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshedAt, setRefreshedAt] = useState<Record<string, string>>({});
  const sessionsRef = useRef<Map<string, AskSession>>(new Map());
  const timer = useRef<number | null>(null);

  /** 每 pin 一个会话实例(重放面:无会话身份,零多轮记忆);render 期幂等建。 */
  function sessionFor(pin: Pin): AskSession {
    let s = sessionsRef.current.get(pin.id);
    if (!s) {
      s = createAskSession({ getPageContext: () => ({ route: pin.route, selection: [] }) });
      sessionsRef.current.set(pin.id, s);
    }
    return s;
  }

  // biome-ignore lint/correctness/useExhaustiveDependencies: sessionFor 只触 sessionsRef(组件生命周期稳定的 Map),首渲染闭包即正确
  const replay = useCallback(async (list: Pin[]) => {
    // busy 闸(2026-10-15 收口):任一目标 pin 仍在途(慢流>60s)即跳过本轮,
    // 严禁与上一轮重叠 ask(旧实现无闸,慢流下 interval 与手动刷新并发)
    if (list.some((p) => sessionsRef.current.get(p.id)?.getState().busy)) return;
    setRefreshing(true);
    await Promise.all(list.map((pin) => sessionFor(pin).ask(pin.question, { replace: true })));
    const at = new Date().toLocaleTimeString();
    setRefreshedAt((prev) => ({ ...prev, ...Object.fromEntries(list.map((p) => [p.id, at])) }));
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
    sessionsRef.current.delete(id);
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

      {/* 服务额度(积分)只读卡(2026-10-21 用量配额闸):常驻看板即工作台首页,
          余额+最近流水一屏可见;不加菜单(RBAC 菜单树在服务端种子)。 */}
      {!bigScreen && <CreditsCard />}

      {pins.length === 0 && (
        <div className="rounded-xl border border-dashed border-zinc-300 px-4 py-10 text-center text-xs text-zinc-400">
          还没有钉卡 —— 在任意页面的数据分析助手里点结果卡下方的「📌 钉看板」
        </div>
      )}

      <div className={bigScreen ? 'grid grid-cols-2 gap-4 xl:grid-cols-3' : 'space-y-4'}>
        {pins.map((pin) => (
          <PinCard
            key={pin.id}
            pin={pin}
            session={sessionFor(pin)}
            refreshedAt={refreshedAt[pin.id] ?? null}
            onRemove={removePin}
          />
        ))}
      </div>
    </div>
  );
}

/** 单钉卡:自订阅其会话(useSyncExternalStore),重放结果/错误帧经会话状态上屏。 */
function PinCard({
  pin,
  session,
  refreshedAt,
  onRemove,
}: {
  pin: Pin;
  session: AskSession;
  refreshedAt: string | null;
  onRemove: (id: string) => void;
}) {
  const { frames, busy } = useAskSession(session);
  const results = frames.filter((f: SessionFrame) => f.event === 'result');
  const failed = frames.find((f) => f.event === 'unsupported' || f.event === 'error');
  return (
    <div className="rounded-2xl border border-zinc-200 bg-white p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm font-medium">{pin.question}</div>
        <div className="flex items-center gap-2 text-[11px] text-zinc-400">
          {refreshedAt && <span>刷新于 {refreshedAt}</span>}
          <Button
            type="button"
            variant="ghost"
            className="h-auto px-0.5 py-0 text-[11px] font-normal text-zinc-400 hover:text-zinc-900"
            onClick={() => onRemove(pin.id)}
          >
            移除
          </Button>
        </div>
      </div>
      {failed && <div className="text-xs text-zinc-500">{String(failed.data.message ?? failed.event)}</div>}
      {results.map((f) => (
        <div key={f.id} className="mb-2">
          <ResultCard data={f.data} />
          {f.data.summary ? (
            <div className="mt-1 text-[11px] leading-relaxed text-zinc-500">
              <span className="mr-1 rounded bg-zinc-100 px-1 py-0.5 text-[10px] text-zinc-500">速览</span>
              {String(f.data.summary)}
            </div>
          ) : null}
        </div>
      ))}
      {/* 诚实空仅在「本轮已完成」时呈现;重放在途把「还没查」说成「查了没有」是假陈述 */}
      {!busy && !failed && !results.length && <div className="text-xs text-zinc-400">本轮无结果(诚实空)</div>}
    </div>
  );
}
