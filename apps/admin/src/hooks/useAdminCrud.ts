import { useState, useMemo, useCallback } from "react";
import { useAdminTenantStore } from "../store/tenantStore";

export interface UseAdminCrudOptions<T> {
  initialData?: T[];
  filterFn?: (
    item: T,
    query: string,
    status: string,
    tenantId: string,
  ) => boolean;
  defaultPageSize?: number;
  tenantKey?: keyof T;
}

export function useAdminCrud<T extends Record<string, any>>({
  initialData = [],
  filterFn,
  defaultPageSize = 10,
  tenantKey = "businessId" as keyof T,
}: UseAdminCrudOptions<T> = {}) {
  const [data, setData] = useState<T[]>(initialData);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(defaultPageSize);

  // 弹窗与抽屉控制状态
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [selectedItem, setSelectedItem] = useState<T | null>(null);
  const [itemToDelete, setItemToDelete] = useState<T | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // 全局租户穿透状态
  const { selectedTenantId } = useAdminTenantStore();

  // 综合过滤数据
  const filteredData = useMemo(() => {
    return data.filter((item) => {
      // 1. 全局租户穿透过滤
      if (selectedTenantId !== "all" && item[tenantKey] !== undefined) {
        if (item[tenantKey] !== selectedTenantId && item[tenantKey] !== "all") {
          return false;
        }
      }

      // 2. 自定义 filterFn
      if (filterFn) {
        return filterFn(item, searchQuery, statusFilter, selectedTenantId);
      }

      // 3. 默认字符串模糊匹配
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase();
        const matchesAnyString = Object.values(item).some((val) =>
          typeof val === "string" ? val.toLowerCase().includes(query) : false,
        );
        if (!matchesAnyString) return false;
      }

      // 4. 默认状态过滤
      if (
        statusFilter &&
        item.status !== undefined &&
        item.status !== statusFilter
      ) {
        return false;
      }

      return true;
    });
  }, [data, selectedTenantId, searchQuery, statusFilter, filterFn, tenantKey]);

  // 分页数据切片
  const paginatedData = useMemo(() => {
    const startIndex = (currentPage - 1) * pageSize;
    return filteredData.slice(startIndex, startIndex + pageSize);
  }, [filteredData, currentPage, pageSize]);

  // 重置筛选
  const handleResetFilters = useCallback(() => {
    setSearchQuery("");
    setStatusFilter("");
    setCurrentPage(1);
  }, []);

  // CRUD 操作方法
  const createItem = useCallback((newItem: T) => {
    setData((prev) => [newItem, ...prev]);
    setIsCreateOpen(false);
  }, []);

  const updateItem = useCallback(
    (idKey: keyof T, updatedItem: T) => {
      setData((prev) =>
        prev.map((item) =>
          item[idKey] === updatedItem[idKey]
            ? { ...item, ...updatedItem }
            : item,
        ),
      );
      setIsEditOpen(false);
      if (selectedItem && selectedItem[idKey] === updatedItem[idKey]) {
        setSelectedItem(updatedItem);
      }
    },
    [selectedItem],
  );

  const deleteItem = useCallback(
    (idKey: keyof T, idValue: any) => {
      setData((prev) => prev.filter((item) => item[idKey] !== idValue));
      setItemToDelete(null);
      if (selectedItem && selectedItem[idKey] === idValue) {
        setIsDrawerOpen(false);
        setSelectedItem(null);
      }
    },
    [selectedItem],
  );

  const openDrawer = useCallback((item: T) => {
    setSelectedItem(item);
    setIsDrawerOpen(true);
  }, []);

  const closeDrawer = useCallback(() => {
    setIsDrawerOpen(false);
  }, []);

  const openEdit = useCallback((item: T) => {
    setSelectedItem(item);
    setIsEditOpen(true);
  }, []);

  return {
    data,
    setData,
    filteredData,
    paginatedData,
    total: filteredData.length,
    currentPage,
    setCurrentPage,
    pageSize,
    setPageSize,
    searchQuery,
    setSearchQuery,
    statusFilter,
    setStatusFilter,
    handleResetFilters,
    // 弹窗与抽屉
    isCreateOpen,
    setIsCreateOpen,
    isEditOpen,
    setIsEditOpen,
    isDrawerOpen,
    setIsDrawerOpen,
    selectedItem,
    setSelectedItem,
    itemToDelete,
    setItemToDelete,
    isDeleting,
    setIsDeleting,
    openDrawer,
    closeDrawer,
    openEdit,
    // CRUD 动作
    createItem,
    updateItem,
    deleteItem,
  };
}
