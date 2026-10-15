// analytics ask SSE 帧类型(F4,2026-10-03):与 engine_py/analytics/graph.py
// 帧形一一对应 —— `data: any` 换成形状契约,ResultCard / AskTranscript 消费的
// 每个字段在此有出处。类型放消费侧 lib(merchant-admin 无 packages/types 依赖,
// 夜审 F6 裁决不重开);SSE 帧形状属冻结面,变更须同批改这里与 graph.py。

export type AskCardColumn = { key: string; label: string };
export type AskRow = Record<string, unknown>;

// table 卡:columns/rows 恒在(engine build_cards 表格基座必带);text 卡:诚实空/说明
export type AskCard =
  | { type: 'table'; title?: string; columns: AskCardColumn[]; rows: AskRow[]; caliber?: string }
  | { type: 'text'; text?: string; caliber?: string };

export type AskClarifyOption = {
  key?: string;
  label: string;
  intent?: { metric: string; direction: string };
};

/** 信任章(ADR-0010 分层信任架构):机器语义字段,呈现层严禁解析口径文案推断。
 * verified=核验模板(T0)/ composed=语义层组合(T1)/ explored=探索生成(T2)。 */
export type AskTrust = 'verified' | 'composed' | 'explored';

/** 各帧族字段的可选并集(渲染层按 event 分派后字段必然在);新帧字段同批登记。 */
export interface AskFrameData {
  // result 帧
  title?: string;
  metric?: string;
  unit?: string;
  caliber?: string;
  chart?: string | null;
  summary?: string | null;
  rows?: AskRow[];
  cards?: AskCard[];
  // 信任章(ADR-0010):缺省 = verified(历史帧无此键,渲染层按默认态处理);
  // explored 帧必带 generatedSql(折叠展示,口径可审计)
  trust?: AskTrust;
  generatedSql?: string;
  // B2 归因叙事(ADR-0011):独立帧区块 + 「AI 推断(非数据)」章 —— 与数据
  // 列视觉分离;数字可溯源硬校验在引擎侧,不过则该键缺席
  narrative?: { text: string };
  // clarify 帧(2026-10-03 起一等公民 Clarify.to_frame)
  clarifyKind?: 'metric' | 'entity';
  question?: string;
  options?: AskClarifyOption[];
  originalQuestion?: string;
  // unsupported / error 帧
  message?: string;
  detail?: string;
  // 客户端 error 帧的断线恢复句柄(ask-session 会话层物化;服务端 error 帧无此键)
  resume?: AskResumeHandle;
  // 终局帧反馈回查键(反馈闭环 v3.1):result/unsupported/error 由引擎
  // _with_trace 盖章(tr_<hex12>),clarify 中间态不带;POST feedback 原样回传
  traceId?: string;
  // start 帧
  staff?: string;
  role?: string;
  askId?: string;
}

export type AskFrame = { event: string; data: AskFrameData };

// ─── 会话层标注(ask-session):客户端自造帧与宿主标注,单点归此册 ───
// 服务端只发 start/heartbeat/result/clarify/unsupported/error;user/pending
// 与带恢复句柄的 error 是 ask-session 的客户端自造帧,与服务端帧形同册
// (F4 消费侧 lib 裁决)。组件内严禁再自造并行类型(2026-10-15「Ask 会话」
// 四表面收敛裁决,见 CONTEXT.md;此前 FloatingAgent 内的 AgentFrame/
// AgentFrameData/__question 私货通道就此退役)。

export type AskFrameEvent = 'start' | 'heartbeat' | 'user' | 'pending' | 'result' | 'clarify' | 'unsupported' | 'error';

/** 断线恢复句柄(挂 error 帧 data.resume):流留 Redis 600s、生产者断开不停算,
 *  携 askId+lastEventId 重进 ask 的 resume 参数只补 seq>last 不重算;
 *  question/pageContext 由会话层带入(AskStreamError 错误对象只携 askId/
 *  lastEventId)。pageContext 缺席 = 无上下文面(无勾选/无路由上行)。 */
export type AskResumeHandle = {
  askId: string;
  lastEventId: number;
  question: string;
  pageContext?: object;
};

/** 答案反馈判定(反馈闭环 v3.1):提交真源在 api.feedback.submit,组件只持闩锁态。 */
export type FeedbackVerdict = 'up' | 'down';

/** 会话帧 = 服务端帧 + 会话层扩充:id 供按帧回写(渲染层按下标回写会错位);
 *  question 标注产生该帧的问句(钉看板/存报告读取 —— wrapper 级标注,严禁
 *  __question 私货通道复活);saved/rated 为宿主动作标注,随历史持久化。 */
export type SessionFrame = AskFrame & {
  id: number;
  question?: string;
  saved?: boolean;
  rated?: FeedbackVerdict;
};
