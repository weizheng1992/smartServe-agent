// 本体知识层编译产物 —— GENERATED,手改无效(漂移门 test_codegen_sync)。
// 源头:ontology/application/actions.yaml(经 ontology/registry.py emit_typescript)。
// 再生成:仓库根执行 `services/.venv/bin/python ontology/registry.py --write-all`。
// 前端接线(消费本文件的包)随首个真实消费方落地 —— 零消费方不预建装配。

export const FACES = ['customer', 'operator', 'staff_review', 'spi'] as const;
export type Face = (typeof FACES)[number];

export const APPROVAL_ACTIONS = [
  'approve',
  'reject',
  'cancel',
  'start_human_takeover',
  'human_message',
  'human_finish',
  'release_takeover',
  'human_reply',
] as const;
export type ApprovalAction = (typeof APPROVAL_ACTIONS)[number];

export const ACTION_FACES: Record<ApprovalAction, readonly Face[]> = {
  approve: ['customer', 'staff_review', 'spi'],
  reject: ['customer', 'staff_review', 'spi'],
  cancel: ['customer', 'spi'],
  start_human_takeover: ['customer', 'spi'],
  human_message: ['operator', 'spi'],
  human_finish: ['operator', 'spi'],
  release_takeover: ['operator', 'spi'],
  human_reply: ['spi'],
};

export const TS_GHOST_ACTIONS = ['reply'] as const;
export const DEFAULT_REFUND_AUTO_APPROVAL_LIMIT = 50.0;
