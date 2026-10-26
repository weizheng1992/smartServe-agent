// Ask 会话(2026-10-15「Ask 会话」四表面收敛,CONTEXT.md 有词条):一次与
// Data Agent 的问答交互(提问 → 帧流 → 终局)的单一 deep module。
// 悬浮面板 / analytics 全屏 / 看板重放是其上的 adapter;ResultCard 是其下方
// 的唯一渲染缝。会话拥有:帧数组与 id 纪律、heartbeat/start 过滤、
// AskStreamError 恢复句柄物化(error 帧 + 「恢复结果」不重算)、pageContext
// 组装(勾选上行 + 会话身份)、clarify 追问句组装、rated 反馈闩锁。
// api.ask transport 面不动(ADR-0013 / test_analytics_ask_replay 钉死),
// 本模块是其 UI 侧唯一消费者 —— AskStreamError 的句柄细节到此为止,不再
// 泄漏给任何调用方。
//
// 会话身份 = 多轮记忆开关:getSessionId 缺席(重放类面)时 payload 不带
// sessionId,服务端 session_store 双闸零读零写(24h TTL 上下文不受打扰)。
// 看板重放刻意不接 resume:重放=刷新,刷新的真义是要新数据 —— resume 只会
// 取回 600s 内缓存的旧帧,恰好毁掉刷新目的;60s 全量重算不是缺陷是语义。
import {
  type AskClarifyOption,
  type AskFrame,
  type AskFrameData,
  type FeedbackVerdict,
  type SessionFrame,
} from '@/lib/analytics-frames';
import { AskStreamError, api } from '@/lib/api';
import { useEffect, useSyncExternalStore } from 'react';

export type AskSessionState = {
  frames: SessionFrame[];
  /** 一次 ask 在途(恢复也算):输入闸与「正在解析」提示共用 */
  busy: boolean;
  /** rate 单飞闩锁:正在提交反馈的帧 id(渲染层禁用该帧按钮防双击) */
  rateBusyId: number | null;
};

export type AskSessionConfig = {
  /** 多轮记忆开关:返回当前 sessionId 随 payload 上行(服务端按此键存取多轮
   *  上下文);不传/返回 undefined = payload 不带 sessionId(重放类面)。 */
  getSessionId?: () => string | undefined;
  /** pageContext 组装(route + 勾选上行);sessionId 由会话统一附加,此处不带 */
  getPageContext?: () => object | undefined;
  /** 历史持久化(对话面板类面专用):构造时 load 回放,变更后拖尾合流 save;
   *  load 返回 null = 无历史/坏档。不传 = 不持久化(全屏/看板)。 */
  history?: { load: () => SessionFrame[] | null; save: (frames: SessionFrame[]) => void };
  /** 反馈提交注入点(默认 api.feedback.submit;测试缝) */
  submitFeedback?: (p: { traceId: string; verdict: FeedbackVerdict; note?: string }) => Promise<unknown>;
  /** 测试注入:落盘合流窗口 ms(默认 800,夜审 2026-09-29 防逐帧全量写) */
  debounceMs?: number;
  /** 历史上限帧数(默认 60) */
  historyLimit?: number;
};

export type AskSession = {
  /** 提问:user/pending 即时上屏 → api.ask 流式逐帧入列(heartbeat/start 不入
   *  对话流;result 帧标注 question)→ 终局摘 pending。断线:已收帧保留 +
   *  错误帧携恢复句柄(AskStreamError.frames 已随 onFrame 上屏,严禁重复追加)。
   *  replace=true(重放面):成功后整轮换帧防旧结果残留,失败保旧帧 + 错误帧。 */
  ask(question: string, opts?: { replace?: boolean }): Promise<void>;
  /** 断线恢复:按帧携句柄重进流只补不重算;成功/再失败都连旧错误帧一起摘
   *  (不堆「恢复结果」按钮),失败时恢复补投的部分帧已随 onFrame 上屏。 */
  resume(frameId: number): Promise<void>;
  /** 反馈闩锁:同 traceId 组尾判定在渲染层(isFeedbackTail);此处乐观置
   *  rated → 提交 → 失败回滚 + 「反馈失败」错误帧。 */
  rate(frameId: number, verdict: FeedbackVerdict, note?: string): Promise<void>;
  /** 宿主动作成功标注(存为报告防重复提交),随历史持久化。 */
  markSaved(frameId: number): void;
  /** 宿主动作失败落错误帧(如存报告失败):与流错误同形,诚实呈现。 */
  pushError(message: string): void;
  /** 新对话:清空帧;非空→空立即落盘空数组(同步语义),空→空不写。 */
  reset(): void;
  /** 卸载前把未落盘历史立即写盘(防抖尾帧不丢)。 */
  flush(): void;
  getState(): AskSessionState;
  subscribe(fn: () => void): () => void;
};

export function createAskSession(config: AskSessionConfig = {}): AskSession {
  const submitFeedback =
    config.submitFeedback ??
    ((p: { traceId: string; verdict: FeedbackVerdict; note?: string }) => api.feedback.submit(p));
  const limit = config.historyLimit ?? 60;
  const debounceMs = config.debounceMs ?? 800;

  let seq = 0;
  let frames: SessionFrame[] = [];
  let busy = false;
  let rateBusyId: number | null = null;
  let snapshot: AskSessionState = { frames, busy, rateBusyId };
  const listeners = new Set<() => void>();
  let saveTimer: ReturnType<typeof setTimeout> | null = null;
  let prevLen = 0;

  // 历史回放(坏档/异形行由 load 实现自管);id 续排防写回撞车
  const restored = config.history?.load() ?? null;
  if (Array.isArray(restored) && restored.length) {
    // 一次性升级:旧历史的 __question 私货通道迁移为帧级 question 标注
    // (钉看板/存报告在旧帧上不再拿到空问句)
    frames = restored.slice(-limit).map((f) => {
      const legacy = (f.data as { __question?: string }).__question;
      return legacy && !f.question ? { ...f, question: legacy } : f;
    });
    seq = frames.reduce((m, f) => Math.max(m, Number(f.id) || 0), 0);
    prevLen = frames.length;
    snapshot = { frames, busy, rateBusyId };
  }

  /** 落盘纪律(自面板时代继承):非空→空立即落盘空数组;空→空(挂载初态)
   *  不写,避免把待恢复历史抹掉;其余拖尾合流。 */
  function commit() {
    if (config.history) {
      const wasPopulated = prevLen > 0;
      prevLen = frames.length;
      if (saveTimer) {
        clearTimeout(saveTimer);
        saveTimer = null;
      }
      if (frames.length === 0) {
        if (wasPopulated) config.history.save([]);
      } else {
        saveTimer = setTimeout(() => config.history?.save(frames.slice(-limit)), debounceMs);
      }
    }
    snapshot = { frames, busy, rateBusyId };
    for (const fn of listeners) fn();
  }

  function appendError(err: unknown, question: string, pageContext?: object) {
    frames = [
      ...frames,
      {
        id: ++seq,
        event: 'error',
        data: {
          message: String(err),
          // 恢复句柄:流留 Redis 600s、生产者断开不停算,「恢复结果」不重算
          ...(err instanceof AskStreamError
            ? {
                resume: {
                  askId: err.askId,
                  lastEventId: err.lastEventId,
                  question,
                  ...(pageContext ? { pageContext } : {}),
                },
              }
            : {}),
        },
      },
    ];
  }

  /** 流式帧入列:onFrame 与 AskStreamError.frames 同源(api.ask 解析回调逐帧
   *  触发),已上屏帧严禁从错误对象重复追加。 */
  function ingest(f: AskFrame, question: string) {
    // 心跳/start 是传输层帧,不入对话流(渲染成气泡曾刷屏/错位)
    if (f.event === 'heartbeat' || f.event === 'start') return;
    frames = [
      ...frames,
      {
        id: ++seq,
        event: f.event,
        data: f.data,
        ...(f.event === 'result' ? { question } : {}),
      },
    ];
  }

  async function ask(question: string, opts?: { replace?: boolean }) {
    const q = question.trim();
    if (!q || busy) return;
    busy = true;
    const replace = opts?.replace === true;
    // 重放面:旧帧全程保留(刷新中途不闪空),本轮帧缓冲,成功才整轮替换,
    // 失败还原旧面 + 错误帧;对话面:user/pending 追加,流式帧逐帧入列
    const prev = frames;
    let turn: SessionFrame[] = [];
    const user: SessionFrame = { id: ++seq, event: 'user', data: { message: q } };
    const pendingId = ++seq;
    const pending: SessionFrame = { id: pendingId, event: 'pending', data: {} };
    frames = [...frames, user, pending];
    commit();
    const pc = pageContext();
    const onFrame = (f: AskFrame) => {
      if (f.event === 'heartbeat' || f.event === 'start') return;
      const sf: SessionFrame = {
        id: ++seq,
        event: f.event,
        data: f.data,
        ...(f.event === 'result' ? { question: q } : {}),
      };
      frames = [...frames, sf];
      if (replace) turn = [...turn, sf];
      commit();
    };
    try {
      await api.ask(q, pc, onFrame);
      frames = replace ? turn : frames.filter((f) => f.id !== pendingId);
    } catch (err) {
      frames = replace ? prev : frames.filter((f) => f.id !== pendingId);
      appendError(err, q, pc);
    }
    busy = false;
    commit();
  }

  async function resume(frameId: number) {
    const frame = frames.find((f) => f.id === frameId);
    const handle = frame?.data.resume;
    if (!handle || busy) return;
    busy = true;
    const pendingId = ++seq;
    frames = [...frames, { id: pendingId, event: 'pending', data: {} }];
    commit();
    try {
      // 断线续传关键参:首连即带 askId+lastEventId,服务端只补 seq>last 不重算
      await api.ask(handle.question, handle.pageContext, (f) => ingest(f, handle.question), {
        askId: handle.askId,
        lastEventId: handle.lastEventId,
      });
      // 连旧错误帧一起摘:恢复成功后不留失效的「恢复结果」按钮
      frames = frames.filter((f) => f.id !== pendingId && f.id !== frameId);
    } catch (err) {
      // 恢复再失败只留最新句柄,不堆「恢复结果」按钮;补投的部分帧已随 onFrame 上屏
      frames = frames.filter((f) => f.id !== pendingId && f.id !== frameId);
      appendError(err, handle.question, handle.pageContext);
    }
    busy = false;
    commit();
  }

  async function rate(frameId: number, verdict: FeedbackVerdict, note?: string) {
    const frame = frames.find((f) => f.id === frameId);
    const traceId = String(frame?.data.traceId || '');
    if (!frame || !traceId || rateBusyId !== null) return;
    rateBusyId = frameId;
    const prior = frame.rated;
    frames = frames.map((f) => (f.id === frameId ? { ...f, rated: verdict } : f));
    commit();
    try {
      await submitFeedback({ traceId, verdict, note });
    } catch (err) {
      frames = frames
        .map((f) => (f.id === frameId ? { ...f, rated: prior } : f))
        .concat({ id: ++seq, event: 'error', data: { message: `反馈失败:${String(err)}` } });
      commit();
    }
    rateBusyId = null;
    commit();
  }

  function pageContext(): object | undefined {
    const ctx = config.getPageContext?.();
    const sessionId = config.getSessionId?.();
    if (!ctx && !sessionId) return undefined;
    return { ...(ctx || {}), ...(sessionId ? { sessionId } : {}) };
  }

  return {
    ask,
    resume,
    rate,

    markSaved(frameId: number) {
      frames = frames.map((f) => (f.id === frameId ? { ...f, saved: true } : f));
      commit();
    },

    pushError(message: string) {
      frames = [...frames, { id: ++seq, event: 'error', data: { message } }];
      commit();
    },

    reset() {
      frames = [];
      if (saveTimer) {
        clearTimeout(saveTimer);
        saveTimer = null;
      }
      // 「非空→空」立即落盘空数组(清空同步语义);prevLen 归零后由 commit 兜底
      if (config.history && prevLen > 0) {
        prevLen = 0;
        config.history.save([]);
      }
      commit();
    },

    flush() {
      if (saveTimer) {
        clearTimeout(saveTimer);
        saveTimer = null;
      }
      if (config.history && frames.length > 0) config.history.save(frames.slice(-limit));
    },

    getState: () => snapshot,
    subscribe(fn: () => void) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}

/** 反馈按轮次分组(反馈闭环 v3.1):同 traceId 连续帧(场景包子帧)只在组尾
 *  出按钮;traceId 缺失(error/clarify/旧历史帧)不渲染。此前在悬浮面板与
 *  全屏 transcript 各抄一份逐字相同的谓词,现单点在此。 */
export function isFeedbackTail(visible: readonly AskFrame[], i: number): boolean {
  const traceId = String(visible[i]?.data.traceId || '');
  const next = visible[i + 1];
  return Boolean(traceId) && (!next || !next.data.traceId || next.data.traceId !== traceId);
}

/** clarify → 追问句组装(单点,含 entity 分支):指标歧义走「按{label}的商品
 *  排行」模板;实体反问保留原问题上下文组合回问。触发方式由 surface 自定
 *  (面板填输入框可改后发送,全屏直接追问),组装语义全站唯一。 */
export function clarifyAskQuestion(data: AskFrameData, option: AskClarifyOption): string {
  if (data.clarifyKind === 'entity' || data.clarifyKind === 'time') {
    // time(P0① 时间口径反问):「原句(最近7天)」形回问 —— 预设窗在引擎
    // TIME_PATTERNS 中先于闭集外时间词命中,所选口径必然生效
    return data.originalQuestion ? `${data.originalQuestion}(${option.label})` : option.label;
  }
  return `按${option.label}的商品排行`;
}

/** 薄 hook adapter:core 经 useSyncExternalStore 绑进 React;卸载时 flush
 *  尾帧(防抖未到的落盘不丢)。 */
export function useAskSession(session: AskSession): AskSessionState {
  const state = useSyncExternalStore(session.subscribe, session.getState);
  useEffect(() => () => session.flush(), [session]);
  return state;
}

/** 面板/全屏共用的会话身份:浏览器侧稳定 session_id(merchant-admin.session),
 *  服务端 Redis 按此键存 24h 多轮上下文;缺席自举。一个员工同一时刻只有一
 *  个当前身份 —— 面板「新对话」轮转后,全屏页下一问随入新会话。 */
export function currentAskSessionId(): string {
  let sid = localStorage.getItem('merchant-admin.session');
  if (!sid) {
    sid = `s-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    localStorage.setItem('merchant-admin.session', sid);
  }
  return sid;
}
