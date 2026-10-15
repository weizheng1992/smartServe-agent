import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from 'ui';

const SENTINEL = '__unset_optional__';

/** 可选空值 Select(2026-10-15 候选③):把「Radix SelectItem 禁空串」两律封装为
 *  组件 —— 真·可选空值在内部走哨兵,onValueChange 单点映射回 '',哨兵物理上
 *  进不了任何 API payload。此前 4 文件 6 站点各自记忆此律,映射直接贴在写库
 *  payload 边界(staff-table `dept: v === UNSET ? '' : v`),写漏一次哨兵即入库。
 *
 *  占位(不可选,「— 选择负责人 —」)不用本组件:走 SelectValue placeholder +
 *  受控空值;长列表(20+ 项)走 searchable-select。 */
export function OptionalSelect({
  value,
  onChange,
  options,
  emptyLabel,
  id,
  ariaLabel,
  className,
}: {
  /** '' = 未选(显示 emptyLabel 项);其余值原样透传。 */
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
  /** 空值项文案(「未分配/未定级/作为顶级」)。 */
  emptyLabel: string;
  id?: string;
  ariaLabel?: string;
  className?: string;
}) {
  return (
    <Select value={value || SENTINEL} onValueChange={(v) => onChange(v === SENTINEL ? '' : v)}>
      <SelectTrigger id={id} aria-label={ariaLabel} className={className}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={SENTINEL}>{emptyLabel}</SelectItem>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
