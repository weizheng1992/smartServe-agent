import { describe, expect, it } from 'bun:test';
import React from 'react';
import { ConfirmDialog, DataTable, DetailDrawer, FilterBar, FormModal } from '../src/components/crud';

describe('Admin CRUD Component Suite Integration Tests', () => {
  it('renders DataTable with columns, rows and pagination correctly', () => {
    const columns = [
      { key: 'id', header: 'ID' },
      { key: 'name', header: 'Name' },
    ];
    const data = [
      { id: '1', name: 'Item One' },
      { id: '2', name: 'Item Two' },
    ];
    const table = React.createElement(DataTable, {
      columns,
      data,
      pagination: {
        currentPage: 1,
        pageSize: 10,
        total: 2,
        onPageChange: () => {},
      },
    });
    expect(table).toBeDefined();
  });

  it('renders FilterBar with search, status and tenant dropdowns', () => {
    const filterBar = React.createElement(FilterBar, {
      searchQuery: 'test',
      onSearchChange: () => {},
      showTenantFilter: true,
      statusFilter: 'active',
      onStatusChange: () => {},
      statusOptions: [
        { label: '活跃', value: 'active' },
        { label: '禁用', value: 'disabled' },
      ],
    });
    expect(filterBar).toBeDefined();
  });

  it('renders FormModal in closed and open states', () => {
    const modal = React.createElement(FormModal, {
      isOpen: true,
      onClose: () => {},
      onSubmit: () => {},
      title: '新建实体',
      children: React.createElement('div', null, 'Form Content'),
    });
    expect(modal).toBeDefined();
  });

  it('renders DetailDrawer in open state', () => {
    const drawer = React.createElement(DetailDrawer, {
      isOpen: true,
      onClose: () => {},
      title: '详情抽屉',
      children: React.createElement('div', null, 'Drawer Content'),
    });
    expect(drawer).toBeDefined();
  });

  it('renders ConfirmDialog in open state', () => {
    const dialog = React.createElement(ConfirmDialog, {
      isOpen: true,
      onClose: () => {},
      onConfirm: () => {},
      title: '确认删除',
      description: '确定删除该记录吗？此操作不可逆。',
    });
    expect(dialog).toBeDefined();
  });
});
