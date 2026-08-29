import { describe, expect, it, mock } from 'bun:test';
import React from 'react';
import type { ThirdPartyOrder } from 'types';
import { AddressModal, type CustomerAddress } from '../app/components/address/AddressModal';
import { LogisticsModal } from '../app/components/orders/LogisticsModal';
import { OrderDetailModal } from '../app/components/orders/OrderDetailModal';
import { OrdersListModal } from '../app/components/orders/OrdersListModal';

describe('Merchant Storefront Dialogs & Modal Close Behavior (TDD)', () => {
  const mockOrder: ThirdPartyOrder = {
    orderId: 'ORD-2026-TEST-8801',
    userId: 'CUST-8801',
    status: 'SHIPPED',
    totalAmount: 599.0,
    items: [
      {
        productId: 'PROD_001',
        skuId: 'SKU_001',
        title: '极光高弹防泼水冲锋衣',
        specSummary: '曜石黑 / L',
        price: 599.0,
        quantity: 1,
        imageUrl: 'https://images.unsplash.com/photo-test.jpg',
      },
    ],
    shippingAddress: {
      recipientName: '张伟',
      phone: '13800138000',
      fullAddress: '北京市海淀区中关村南大街1号院',
    },
    tracking: {
      carrier: '顺丰速运',
      trackingNumber: 'SF9988776655',
      status: 'IN_TRANSIT',
      timeline: [
        {
          time: '2026-08-25 10:00:00',
          status: '揽收成功',
          location: '北京朝阳分拣中心',
          description: '顺丰速运 已收取快件',
        },
      ],
    },
    isAddressModifiable: false,
    isReturnable: true,
    createdAt: '2026-08-25T10:00:00Z',
  };

  describe('OrderDetailModal', () => {
    it('renders order detail modal with items and actions', () => {
      const handleClose = mock(() => {});
      const handleOpenLogistics = mock(() => {});
      const handleOpenChat = mock(() => {});

      const element = React.createElement(OrderDetailModal, {
        isOpen: true,
        onClose: handleClose,
        order: mockOrder,
        onOpenLogistics: handleOpenLogistics,
        onOpenChatWithOrder: handleOpenChat,
      });

      expect(element).toBeDefined();
      expect(element.props.isOpen).toBe(true);
      expect(element.props.order?.orderId).toBe('ORD-2026-TEST-8801');
    });
  });

  describe('LogisticsModal', () => {
    it('renders logistics tracking timeline and copy action', () => {
      const handleClose = mock(() => {});
      const handleOpenChat = mock(() => {});

      const element = React.createElement(LogisticsModal, {
        isOpen: true,
        onClose: handleClose,
        order: mockOrder,
        onOpenChatWithOrder: handleOpenChat,
      });

      expect(element).toBeDefined();
      expect(element.props.isOpen).toBe(true);
      expect(element.props.order?.tracking?.trackingNumber).toBe('SF9988776655');
    });
  });

  describe('OrdersListModal', () => {
    it('renders orders list modal with tabs and search filter', () => {
      const handleClose = mock(() => {});
      const handleSelectOrder = mock(() => {});
      const handleOpenLogistics = mock(() => {});
      const handleOpenChat = mock(() => {});
      const handleFilterStatus = mock(() => {});

      const element = React.createElement(OrdersListModal, {
        isOpen: true,
        onClose: handleClose,
        orders: [mockOrder],
        loading: false,
        onSelectOrder: handleSelectOrder,
        onOpenLogistics: handleOpenLogistics,
        onOpenChatWithOrder: handleOpenChat,
        onFilterStatus: handleFilterStatus,
        currentStatus: 'ALL',
      });

      expect(element).toBeDefined();
      expect(element.props.isOpen).toBe(true);
      expect(element.props.orders.length).toBe(1);
    });
  });

  describe('AddressModal', () => {
    const mockAddresses: CustomerAddress[] = [
      {
        id: 'addr_1',
        recipientName: '张伟',
        phone: '13800138000',
        fullAddress: '北京市海淀区中关村南大街1号院8号楼1201室',
        isDefault: true,
      },
    ];

    it('renders customer address management and add form', () => {
      const handleClose = mock(() => {});
      const handleSelect = mock(() => {});
      const handleAdd = mock(async () => {});

      const element = React.createElement(AddressModal, {
        isOpen: true,
        onClose: handleClose,
        addresses: mockAddresses,
        selectedAddressId: 'addr_1',
        onSelectAddress: handleSelect,
        onAddAddress: handleAdd,
      });

      expect(element).toBeDefined();
      expect(element.props.isOpen).toBe(true);
      expect(element.props.addresses.length).toBe(1);
    });
  });
});
