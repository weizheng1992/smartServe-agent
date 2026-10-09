import { type ComponentProps, forwardRef } from 'react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow, cn } from 'ui';

// ui(shadcn)Table 的紧凑密度预设:仓库页面表格一贯是 px-4 py-2 / 13px 的
// 数据密集风,ui Table 默认 h-12 表头 / p-4 单元格过松。cn(defaults, className)
// 中 caller 类在后,tailwind-merge 保证此处的密度类可被使用处再覆盖
// (如条件色 text-rose-600、选中态 bg-blue-50/60、列宽 w-8)。

/** 紧凑数据表(text-[13px];仍带 ui Table 的 overflow-auto 包裹)。 */
export const DenseTable = forwardRef<HTMLTableElement, ComponentProps<typeof Table>>(({ className, ...props }, ref) => (
  <Table ref={ref} className={cn('w-full text-[13px]', className)} {...props} />
));
DenseTable.displayName = 'DenseTable';

export const DenseTableHeader = TableHeader;
export const DenseTableBody = TableBody;

export const DenseTableRow = forwardRef<HTMLTableRowElement, ComponentProps<typeof TableRow>>(
  ({ className, ...props }, ref) => (
    <TableRow ref={ref} className={cn('border-b border-zinc-50 hover:bg-transparent', className)} {...props} />
  ),
);
DenseTableRow.displayName = 'DenseTableRow';

export const DenseTableHead = forwardRef<HTMLTableCellElement, ComponentProps<typeof TableHead>>(
  ({ className, ...props }, ref) => (
    <TableHead
      ref={ref}
      className={cn('h-auto px-4 py-2 text-[13px] font-medium text-zinc-400', className)}
      {...props}
    />
  ),
);
DenseTableHead.displayName = 'DenseTableHead';

export const DenseTableCell = forwardRef<HTMLTableCellElement, ComponentProps<typeof TableCell>>(
  ({ className, ...props }, ref) => (
    <TableCell ref={ref} className={cn('px-4 py-2 align-middle text-[13px]', className)} {...props} />
  ),
);
DenseTableCell.displayName = 'DenseTableCell';
