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
  // clarify 帧(2026-10-03 起一等公民 Clarify.to_frame)
  clarifyKind?: 'metric' | 'entity';
  question?: string;
  options?: AskClarifyOption[];
  originalQuestion?: string;
  // unsupported / error 帧
  message?: string;
  detail?: string;
  // 终局帧反馈回查键(反馈闭环 v3.1):result/unsupported/error 由引擎
  // _with_trace 盖章(tr_<hex12>),clarify 中间态不带;POST feedback 原样回传
  traceId?: string;
  // start 帧
  staff?: string;
  role?: string;
  askId?: string;
}

export type AskFrame = { event: string; data: AskFrameData };
