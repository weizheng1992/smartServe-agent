import type React from "react";
import { Combobox, Input, Button } from "ui";
import { useAdminTenantStore } from "../../store/tenantStore";

export interface FilterOption {
  label: string;
  value: string;
}

export interface FilterBarProps {
  searchQuery?: string;
  onSearchChange?: (val: string) => void;
  searchPlaceholder?: string;
  statusFilter?: string;
  onStatusChange?: (val: string) => void;
  statusOptions?: FilterOption[];
  showTenantFilter?: boolean;
  tenantFilter?: string;
  onTenantChange?: (val: string) => void;
  onReset?: () => void;
  extraFilters?: React.ReactNode;
  actions?: React.ReactNode;
}

export function FilterBar({
  searchQuery,
  onSearchChange,
  searchPlaceholder = "输入关键字搜索...",
  statusFilter,
  onStatusChange,
  statusOptions,
  showTenantFilter = false,
  tenantFilter,
  onTenantChange,
  onReset,
  extraFilters,
  actions,
}: FilterBarProps) {
  const { selectedTenantId, setSelectedTenantId, tenants } =
    useAdminTenantStore();
  const activeTenant =
    tenantFilter !== undefined ? tenantFilter : selectedTenantId;
  const handleTenantSelect = (val: string) => {
    if (onTenantChange) {
      onTenantChange(val);
    } else {
      setSelectedTenantId(val);
    }
  };

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-3.5 shadow-xs mb-4 flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-2.5 flex-1 min-w-[280px]">
        {/* 关键字搜索框 */}
        {onSearchChange && (
          <div className="relative min-w-[200px] max-w-xs flex-1">
            <svg
              className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
              />
            </svg>
            <Input
              type="text"
              value={searchQuery ?? ""}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder={searchPlaceholder}
              className="w-full pl-9 pr-3 h-8 text-xs bg-slate-50 border-slate-200 text-slate-700 placeholder-slate-400 focus:bg-white transition-colors"
            />
          </div>
        )}

        {/* 状态筛选 */}
        {statusOptions && onStatusChange && (
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            <span>状态:</span>
            <select
              value={statusFilter ?? ""}
              onChange={(e) => onStatusChange(e.target.value)}
              className="h-8 px-2.5 text-xs bg-slate-50 border border-slate-200 rounded-md text-slate-700 focus:outline-hidden focus:border-slate-400 transition-colors"
            >
              <option value="">全部状态</option>
              {statusOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* 商户租户筛选 (Shadcn/UI Combobox) */}
        {showTenantFilter && (
          <Combobox
            label="租户:"
            value={activeTenant}
            onChange={(val) => handleTenantSelect(val)}
            searchPlaceholder="搜索商户名或租户 ID..."
            emptyText="未找到匹配的商户"
            options={tenants.map((t) => ({
              value: t.id,
              label: t.name,
              badge: t.id,
              badgeColor: t.badgeColor,
            }))}
            triggerClassName="h-8 text-xs"
          />
        )}

        {extraFilters}

        {onReset && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onReset}
            className="h-8 px-2.5 text-xs text-slate-500 hover:text-slate-800 hover:bg-slate-100"
          >
            重置筛选
          </Button>
        )}
      </div>

      {/* 右侧动作插槽（如新增按钮） */}
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
