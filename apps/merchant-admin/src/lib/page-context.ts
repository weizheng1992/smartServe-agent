// PageContext 选择上下文(T5 翻新):内存广播 + 实体类型标记。
// 不再入 localStorage —— 残留勾选曾两次静默污染查询(实弹踩坑),选择是
// 一次性会话上下文,随页面会话生灭。跨组件同步走订阅;跨页签不需要。

export type SelectionKind = 'order' | 'spu' | 'customer';
export type SelectionMap = Partial<Record<SelectionKind, string[]>>;

let current: SelectionMap = {};
// kind → (id → 人话标签):商品标题/客户名,供图表标题等人话呈现
const labels: Partial<Record<SelectionKind, Record<string, string>>> = {};
const listeners = new Set<(s: SelectionMap) => void>();

// 旧契约残留一次性清除(迁移 2026-09-22)
try {
  localStorage.removeItem('merchant-admin.selection');
} catch {
  /* 存储不可用忽略 */
}

export function getSelection(): SelectionMap {
  return current;
}

export function getSelectionLabels(): Partial<Record<SelectionKind, Record<string, string>>> {
  return labels;
}

export function setSelectionKind(kind: SelectionKind, ids: string[], labelsById?: Record<string, string>): void {
  const next: SelectionMap = { ...current };
  const uniq = [...new Set(ids)].slice(0, 100);
  if (uniq.length) {
    next[kind] = uniq;
    if (labelsById) labels[kind] = { ...(labels[kind] || {}), ...labelsById };
  } else {
    delete next[kind];
    delete labels[kind];
  }
  current = next;
  emit();
}

export function toggleKindId(kind: SelectionKind, id: string): string[] {
  const ids = new Set(current[kind] || []);
  if (ids.has(id)) ids.delete(id);
  else ids.add(id);
  setSelectionKind(kind, [...ids]);
  return current[kind] || [];
}

export function clearSelection(): void {
  current = {};
  emit();
}

export function subscribe(fn: (s: SelectionMap) => void): () => void {
  listeners.add(fn);
  fn(current);
  return () => {
    listeners.delete(fn);
  };
}

function emit(): void {
  for (const fn of listeners) fn(current);
}
