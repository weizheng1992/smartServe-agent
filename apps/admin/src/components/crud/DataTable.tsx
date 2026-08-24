import type React from 'react';
import { Button, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from 'ui';

export interface Column<T> {
  key: string;
  header: string;
  width?: string;
  align?: 'left' | 'center' | 'right';
  render?: (row: T, index: number) => React.ReactNode;
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  loading?: boolean;
  emptyText?: string;
  onRowClick?: (row: T) => void;
  selectedRowId?: string | number;
  rowKey?: (row: T) => string | number;
  pagination?: {
    currentPage: number;
    pageSize: number;
    total: number;
    onPageChange: (page: number) => void;
  };
}

export function DataTable<T extends Record<string, any>>({
  columns,
  data,
  loading = false,
  emptyText = '暂无数据',
  onRowClick,
  selectedRowId,
  rowKey = (row) => row.id ?? JSON.stringify(row),
  pagination,
}: DataTableProps<T>) {
  const totalPages = pagination ? Math.ceil(pagination.total / pagination.pageSize) : 1;

  return (
    <div className="w-full bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden flex flex-col">
      <div className="overflow-x-auto">
        <Table className="w-full">
          <TableHeader>
            <TableRow className="bg-slate-50/80 hover:bg-slate-50/80 border-b border-slate-200">
              {columns.map((col) => (
                <TableHead
                  key={col.key}
                  style={{ width: col.width }}
                  className={`py-3 px-4 text-xs font-semibold text-slate-500 uppercase tracking-wider ${
                    col.align === 'center' ? 'text-center' : col.align === 'right' ? 'text-right' : 'text-left'
                  }`}
                >
                  {col.header}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody className="divide-y divide-slate-100">
            {loading ? (
              Array.from({ length: 4 }).map((_, idx) => (
                <TableRow key={`skeleton-${idx}`} className="animate-pulse">
                  {columns.map((col) => (
                    <TableCell key={col.key} className="py-4 px-4">
                      <div className="h-4 bg-slate-100 rounded-md w-3/4" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : data.length === 0 ? (
              <TableRow>
                <TableCell colSpan={columns.length} className="py-12 text-center text-slate-400 text-sm">
                  <div className="flex flex-col items-center justify-center gap-2">
                    <svg className="w-8 h-8 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={1.5}
                        d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"
                      />
                    </svg>
                    <span>{emptyText}</span>
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              data.map((row, index) => {
                const currentId = rowKey(row);
                const isSelected = selectedRowId !== undefined && selectedRowId === currentId;
                return (
                  <TableRow
                    key={String(currentId)}
                    onClick={() => onRowClick?.(row)}
                    className={`transition-colors duration-150 ${onRowClick ? 'cursor-pointer' : ''} ${
                      isSelected ? 'bg-slate-50 font-medium text-slate-900' : 'hover:bg-slate-50/70 text-slate-700'
                    }`}
                  >
                    {columns.map((col) => (
                      <TableCell
                        key={col.key}
                        className={`py-3.5 px-4 text-sm ${
                          col.align === 'center' ? 'text-center' : col.align === 'right' ? 'text-right' : 'text-left'
                        }`}
                      >
                        {col.render ? col.render(row, index) : (row[col.key] ?? '-')}
                      </TableCell>
                    ))}
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      {pagination && pagination.total > 0 && (
        <div className="p-3 bg-white border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
          <div>
            共 <span className="font-semibold text-slate-700">{pagination.total}</span> 条数据， 第{' '}
            <span className="font-semibold text-slate-700">{pagination.currentPage}</span> / {Math.max(totalPages, 1)}{' '}
            页
          </div>
          <div className="flex items-center gap-1.5">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={pagination.currentPage <= 1 || loading}
              onClick={() => pagination.onPageChange(pagination.currentPage - 1)}
              className="h-8 px-2.5 text-xs text-slate-600"
            >
              上一页
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={pagination.currentPage >= totalPages || loading}
              onClick={() => pagination.onPageChange(pagination.currentPage + 1)}
              className="h-8 px-2.5 text-xs text-slate-600"
            >
              下一页
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
