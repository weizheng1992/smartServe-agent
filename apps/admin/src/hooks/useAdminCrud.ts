import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAdminTenantStore } from '../store/tenantStore';

export interface UseAdminCrudOptions<T> {
  initialData?: T[];
  fetchList?: (params: {
    tenantId: string;
    page: number;
    pageSize: number;
    query?: string;
    status?: string;
  }) => Promise<{ data: T[]; total?: number } | T[]>;
  createApi?: (item: Partial<T>, tenantId: string) => Promise<T | boolean>;
  updateApi?: (item: T, tenantId: string) => Promise<T | boolean>;
  deleteApi?: (idValue: any, tenantId: string) => Promise<boolean>;
  filterFn?: (item: T, query: string, status: string, tenantId: string) => boolean;
  defaultPageSize?: number;
  tenantKey?: keyof T;
  storageKey?: string;
  onItemCreated?: (item: T) => void;
  onItemUpdated?: (item: T) => void;
  onItemDeleted?: (idValue: any) => void;
}

export function useAdminCrud<T extends Record<string, any>>({
  initialData = [],
  fetchList,
  createApi,
  updateApi,
  deleteApi,
  filterFn,
  defaultPageSize = 10,
  tenantKey = 'businessId' as keyof T,
  storageKey,
  onItemCreated,
  onItemUpdated,
  onItemDeleted,
}: UseAdminCrudOptions<T> = {}) {
  const [data, setData] = useState<T[]>(() => {
    if (typeof window !== 'undefined' && storageKey) {
      try {
        const saved = localStorage.getItem(storageKey);
        if (saved) {
          const parsed = JSON.parse(saved);
          if (Array.isArray(parsed) && parsed.length > 0) {
            return parsed;
          }
        }
      } catch (err) {
        console.warn(`[useAdminCrud] Failed to load localStorage data for ${storageKey}:`, err);
      }
    }
    return initialData;
  });

  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(defaultPageSize);
  const [serverTotal, setServerTotal] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 弹窗与抽屉控制状态
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [selectedItem, setSelectedItem] = useState<T | null>(null);
  const [itemToDelete, setItemToDelete] = useState<T | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // 全局租户穿透状态
  const { selectedTenantId } = useAdminTenantStore();

  // 持久化到 localStorage
  const persistData = useCallback(
    (nextData: T[]) => {
      if (typeof window !== 'undefined' && storageKey) {
        try {
          localStorage.setItem(storageKey, JSON.stringify(nextData));
        } catch (err) {
          console.warn(`[useAdminCrud] Failed to persist data for ${storageKey}:`, err);
        }
      }
    },
    [storageKey],
  );

  // 远程拉取数据
  const refetch = useCallback(async () => {
    if (!fetchList) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await fetchList({
        tenantId: selectedTenantId,
        page: currentPage,
        pageSize,
        query: searchQuery,
        status: statusFilter,
      });

      if (Array.isArray(res)) {
        setData(res);
        setServerTotal(null);
      } else if (res && Array.isArray(res.data)) {
        setData(res.data);
        setServerTotal(res.total ?? res.data.length);
      }
    } catch (err: any) {
      console.error('[useAdminCrud] fetchList error:', err);
      setError(err?.message || '获取数据失败');
    } finally {
      setIsLoading(false);
    }
  }, [fetchList, selectedTenantId, currentPage, pageSize, searchQuery, statusFilter]);

  // 依赖变化时自动重新拉取
  useEffect(() => {
    if (fetchList) {
      refetch();
    }
  }, [refetch, fetchList]);

  // 综合过滤数据 (若使用服务端分页则直接返回 data)
  const filteredData = useMemo(() => {
    if (serverTotal !== null) {
      return data;
    }
    return data.filter((item) => {
      // 1. 全局租户穿透过滤
      if (selectedTenantId !== 'all' && item[tenantKey] !== undefined) {
        const val = item[tenantKey];
        if (val !== selectedTenantId && val !== 'all' && val !== 'global' && val !== 'platform') {
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
          typeof val === 'string' ? val.toLowerCase().includes(query) : false,
        );
        if (!matchesAnyString) return false;
      }

      // 4. 默认状态过滤
      if (statusFilter && item.status !== undefined && item.status !== statusFilter) {
        return false;
      }

      return true;
    });
  }, [data, selectedTenantId, searchQuery, statusFilter, filterFn, tenantKey, serverTotal]);

  // 分页数据切片
  const paginatedData = useMemo(() => {
    if (serverTotal !== null) {
      return data;
    }
    const startIndex = (currentPage - 1) * pageSize;
    return filteredData.slice(startIndex, startIndex + pageSize);
  }, [filteredData, currentPage, pageSize, serverTotal, data]);

  // 重置筛选
  const handleResetFilters = useCallback(() => {
    setSearchQuery('');
    setStatusFilter('');
    setCurrentPage(1);
  }, []);

  // CRUD 操作方法
  const createItem = useCallback(
    async (newItem: Partial<T>) => {
      setIsSubmitting(true);
      setError(null);
      try {
        if (createApi) {
          const res = await createApi(newItem, selectedTenantId);
          if (typeof res === 'object' && res !== null) {
            setData((prev) => [res as T, ...prev]);
            onItemCreated?.(res as T);
          } else {
            await refetch();
          }
        } else {
          setData((prev) => {
            const next = [newItem as T, ...prev];
            persistData(next);
            return next;
          });
          onItemCreated?.(newItem as T);
        }
        setIsCreateOpen(false);
      } catch (err: any) {
        console.error('[useAdminCrud] createItem error:', err);
        setError(err.message || '创建失败');
        throw err;
      } finally {
        setIsSubmitting(false);
      }
    },
    [createApi, selectedTenantId, refetch, persistData, onItemCreated],
  );

  const updateItem = useCallback(
    async (idKey: keyof T, updatedItem: T) => {
      setIsSubmitting(true);
      setError(null);
      try {
        if (updateApi) {
          const res = await updateApi(updatedItem, selectedTenantId);
          if (typeof res === 'object' && res !== null) {
            setData((prev) => prev.map((item) => (item[idKey] === updatedItem[idKey] ? { ...item, ...res } : item)));
            if (selectedItem && selectedItem[idKey] === updatedItem[idKey]) {
              setSelectedItem({ ...selectedItem, ...res });
            }
            onItemUpdated?.(res as T);
          } else {
            await refetch();
          }
        } else {
          setData((prev) => {
            const next = prev.map((item) => (item[idKey] === updatedItem[idKey] ? { ...item, ...updatedItem } : item));
            persistData(next);
            return next;
          });
          if (selectedItem && selectedItem[idKey] === updatedItem[idKey]) {
            setSelectedItem(updatedItem);
          }
          onItemUpdated?.(updatedItem);
        }
        setIsEditOpen(false);
      } catch (err: any) {
        console.error('[useAdminCrud] updateItem error:', err);
        setError(err.message || '更新失败');
        throw err;
      } finally {
        setIsSubmitting(false);
      }
    },
    [updateApi, selectedTenantId, selectedItem, refetch, persistData, onItemUpdated],
  );

  const deleteItem = useCallback(
    async (idKey: keyof T, idValue: any) => {
      setIsDeleting(true);
      setError(null);
      try {
        if (deleteApi) {
          await deleteApi(idValue, selectedTenantId);
        }
        setData((prev) => {
          const next = prev.filter((item) => item[idKey] !== idValue);
          persistData(next);
          return next;
        });
        setItemToDelete(null);
        if (selectedItem && selectedItem[idKey] === idValue) {
          setIsDrawerOpen(false);
          setSelectedItem(null);
        }
        onItemDeleted?.(idValue);
      } catch (err: any) {
        console.error('[useAdminCrud] deleteItem error:', err);
        setError(err.message || '删除失败');
        throw err;
      } finally {
        setIsDeleting(false);
      }
    },
    [deleteApi, selectedTenantId, persistData, selectedItem, onItemDeleted],
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
    total: serverTotal !== null ? serverTotal : filteredData.length,
    currentPage,
    setCurrentPage,
    pageSize,
    setPageSize,
    searchQuery,
    setSearchQuery,
    statusFilter,
    setStatusFilter,
    handleResetFilters,
    isLoading,
    isSubmitting,
    error,
    refetch,
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
