import { afterAll, beforeAll, describe, expect, it } from 'bun:test';
import { NextRequest } from 'next/server';
import { GET as getAdminApprovalsRoute, POST as postAdminApprovalsRoute } from '../app/api/admin/approvals/route';
import { GET as getConversationTimelineRoute } from '../app/api/admin/conversations/[threadId]/route';
import { GET as getAdminOrdersRoute } from '../app/api/admin/orders/route';
import { GET as getAddressesRoute, POST as postAddressesRoute } from '../app/api/store/addresses/route';
import { GET as getStoreChatMessagesRoute } from '../app/api/store/chat/messages/route';
import { POST as postStoreChatRoute } from '../app/api/store/chat/route';
import { GET as getStoreProductsRoute } from '../app/api/store/products/route';
import { POST as postOrderActionRoute } from '../app/spi/v1/orders/action/route';
import { GET as getOrderDetailRoute } from '../app/spi/v1/orders/detail/route';
import { GET as getOrdersListRoute } from '../app/spi/v1/orders/list/route';
import { GET as searchProductsRoute } from '../app/spi/v1/products/search/route';
import { GET as getUserInfoRoute } from '../app/spi/v1/user/info/route';
import { seedMerchantData } from '../src/db/seed';
import { MerchantDomainService } from '../src/services/merchantDomainService';

describe('🚀 Merchant Complete User Journey Suite (三大全链路端到端综合测试)', () => {
  const TEST_PORT = 3019;
  const BASE_URL = `http://localhost:${TEST_PORT}`;
  const tenantId = 'aurora';
  const testUserId = 'CUST-8801';
  let localHttpServer: ReturnType<typeof Bun.serve> | null = null;

  beforeAll(async () => {
    process.env.SPI_BASE_URL_OVERRIDE = BASE_URL;
    // 1. 初始化商户独立数据库种子数据
    await seedMerchantData();

    // 2. 启动测试专用 HTTP 调度器（处理 SPI 与 Store API）
    localHttpServer = Bun.serve({
      port: TEST_PORT,
      async fetch(req) {
        const url = new URL(req.url);
        const nextReq = new NextRequest(req.url, {
          method: req.method,
          headers: req.headers,
          body: req.method === 'POST' ? await req.text() : undefined,
        });

        if (url.pathname === '/spi/v1/user/info') return getUserInfoRoute(nextReq);
        if (url.pathname === '/spi/v1/orders/list') return getOrdersListRoute(nextReq);
        if (url.pathname === '/spi/v1/orders/detail') return getOrderDetailRoute(nextReq);
        if (url.pathname === '/spi/v1/orders/action') return postOrderActionRoute(nextReq);
        if (url.pathname === '/spi/v1/products/search') return searchProductsRoute(nextReq);
        if (url.pathname === '/api/store/products') return getStoreProductsRoute();
        if (url.pathname === '/api/admin/orders') return getAdminOrdersRoute();

        return new Response('Not Found', { status: 404 });
      },
    });
  });

  afterAll(() => {
    if (localHttpServer) {
      localHttpServer.stop();
    }
    delete process.env.SPI_BASE_URL_OVERRIDE;
  });

  // =========================================================================
  // 流程 1: 订单查询 ➔ 选单 ➔ 申请退款 ➔ 审批通过/拒绝 ➔ 状态查询 / 人工客服转接
  // =========================================================================
  describe('【流程一】订单查询 ➔ 选择订单 ➔ 申请退款 ➔ 审批拒绝/通过 ➔ 状态追踪与转人工客服', () => {
    const threadId = `merchant_journey_order_refund_${Date.now()}`;
    const targetOrderId = 'AURORA-ORD-2026-9081';
    let approvalId = '';

    it('1.1 用户查询我的全部订单，系统应返回订单摘要与 order_picker 多模态卡片', async () => {
      const req = new NextRequest('http://localhost:3005/api/store/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: '查询我的全部订单',
          userId: testUserId,
          threadId,
          businessId: tenantId,
        }),
      });

      const res = await postStoreChatRoute(req);
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(json.output).toBeDefined();

      // 验证返回了订单选择器卡片
      expect(Array.isArray(json.cards)).toBe(true);
      const hasOrderPicker = json.cards.some((c: any) => c.type === 'order_picker' || c.type === 'order_card');
      expect(hasOrderPicker).toBe(true);
    }, 120000);

    it('1.2 用户在卡片中选定特定订单，系统应返回精准订单详情与物流卡片', async () => {
      const req = new NextRequest('http://localhost:3005/api/store/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: `已选定订单 ${targetOrderId}，请帮我查询该订单的具体信息和最新物流进度。`,
          userId: testUserId,
          threadId,
          businessId: tenantId,
        }),
      });

      const res = await postStoreChatRoute(req);
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(json.output).toContain(targetOrderId);
    }, 120000);

    it('1.3 用户申请退款，高危金额 (>¥100) 触发 HITL 门禁并挂起为待办审批', async () => {
      const req = new NextRequest('http://localhost:3005/api/store/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: `帮我把订单 ${targetOrderId} 申请退款，原因是不喜欢了。`,
          userId: testUserId,
          threadId,
          businessId: tenantId,
        }),
      });

      const res = await postStoreChatRoute(req);
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(json.output).toMatch(/审核|复核|人工|审批|退款申请/);

      // 从商户后台审批流中查询刚才生成的待审批工单
      const approvalsReq = new NextRequest(`http://localhost:3005/api/admin/approvals?tenantId=${tenantId}`);
      const approvalsRes = await getAdminApprovalsRoute(approvalsReq);
      expect(approvalsRes.status).toBe(200);
      const approvalsJson = await approvalsRes.json();
      expect(approvalsJson.success).toBe(true);
      expect(approvalsJson.approvals.length).toBeGreaterThan(0);

      const targetApproval = approvalsJson.approvals.find(
        (a: any) =>
          a.threadId === threadId ||
          a.actionPayload?.args?.orderId === targetOrderId ||
          a.actionPayload?.orderId === targetOrderId,
      );
      expect(targetApproval).toBeDefined();
      approvalId = targetApproval.id;
    }, 120000);

    it('1.4a 商户后台审批工作台：测试【审批拒绝】分支', async () => {
      const rejectReq = new NextRequest('http://localhost:3005/api/admin/approvals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          approvalId,
          action: 'reject',
          rejectionReason: '商品已拆封影响二次销售，暂不支持退款',
        }),
      });

      const rejectRes = await postAdminApprovalsRoute(rejectReq);
      expect(rejectRes.status).toBe(200);
      const rejectJson = await rejectRes.json();
      expect(rejectJson.success).toBe(true);
      expect(rejectJson.status).toBe('rejected');
    }, 30000);

    it('1.4b 商户后台审批工作台：重新申请并测试【审批通过】分支，推动订单状态流转', async () => {
      // 重新发起退款申请
      const req = new NextRequest('http://localhost:3005/api/store/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: `订单 ${targetOrderId} 存在质量问题包装未拆，请再次申请退款。`,
          userId: testUserId,
          threadId,
          businessId: tenantId,
        }),
      });

      const res = await postStoreChatRoute(req);
      expect(res.status).toBe(200);

      // 获取新的审批工单
      const approvalsReq = new NextRequest(`http://localhost:3005/api/admin/approvals?tenantId=${tenantId}`);
      const approvalsRes = await getAdminApprovalsRoute(approvalsReq);
      const approvalsJson = await approvalsRes.json();
      const newApproval = approvalsJson.approvals.find((a: any) => a.status === 'pending' || a.status === 'waiting');
      expect(newApproval).toBeDefined();

      // 执行审批通过
      const approveReq = new NextRequest('http://localhost:3005/api/admin/approvals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          approvalId: newApproval.id,
          action: 'approve',
        }),
      });

      const approveRes = await postAdminApprovalsRoute(approveReq);
      expect(approveRes.status).toBe(200);
      const approveJson = await approveRes.json();
      expect(approveJson.success).toBe(true);
      expect(approveJson.status).toBe('approved');
    }, 120000);

    it('1.5 用户查询更新后订单状态，并支持一键发起人工客服接管会话', async () => {
      // 查询订单状态
      const orderReq = new NextRequest('http://localhost:3005/api/store/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: `查一下订单 ${targetOrderId} 当前状态`,
          userId: testUserId,
          threadId,
          businessId: tenantId,
        }),
      });
      const orderRes = await postStoreChatRoute(orderReq);
      expect(orderRes.status).toBe(200);

      // 发起人工客服接管 (LiveDesk)
      const takeoverReq = new NextRequest('http://localhost:3005/api/admin/approvals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          threadId,
          action: 'start_human_takeover',
        }),
      });
      const takeoverRes = await postAdminApprovalsRoute(takeoverReq);
      expect(takeoverRes.status).toBe(200);
      const takeoverJson = await takeoverRes.json();
      expect(takeoverJson.success).toBe(true);

      // 人工客服回复
      const replyReq = new NextRequest('http://localhost:3005/api/admin/approvals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          approvalId: takeoverJson.approvalId,
          action: 'human_message',
          humanReply: '您好，您的退款款项已在原路退回处理中，预计1-3个工作日到账。',
        }),
      });
      const replyRes = await postAdminApprovalsRoute(replyReq);
      expect(replyRes.status).toBe(200);

      // 验证会话时间轴中包含该人工客服回复
      const timelineReq = new NextRequest(
        `http://localhost:3005/api/admin/conversations/${threadId}?tenantId=${tenantId}`,
      );
      const timelineRes = await getConversationTimelineRoute(timelineReq, {
        params: Promise.resolve({ threadId }),
      });
      const timelineJson = await timelineRes.json();
      expect(timelineJson.success).toBe(true);
      const messagesList = timelineJson.data?.messages || timelineJson.timeline || timelineJson.messages || [];
      const hasHumanMsg = messagesList.some(
        (m: any) =>
          m.sender === 'human_agent' || m.role === 'human_agent' || (m.content && m.content.includes('原路退回')),
      );
      expect(hasHumanMsg).toBe(true);
    }, 120000);
  });

  // =========================================================================
  // 流程 2: 推销热门商品 ➔ 选中商品 ➔ 加入购物车 ➔ 更改数量 ➔ 删除商品 ➔ 去结算
  // =========================================================================
  describe('【流程二】推销热门商品 ➔ 选中商品 ➔ 加入购物车 ➔ 更改数量 ➔ 删除商品 ➔ 去结算', () => {
    const threadId = `merchant_journey_cart_ecom_${Date.now()}`;
    const ecomUserId = `CUST_ECOM_${Date.now()}`;

    it('2.1 推销热门商品：向用户推荐当季热销款，返回候选商品列表与导购卡片', async () => {
      const req = new NextRequest('http://localhost:3005/api/store/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: '推荐当季热销机能外套',
          userId: ecomUserId,
          threadId,
          businessId: tenantId,
        }),
      });

      const res = await postStoreChatRoute(req);
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(json.output).toContain('精选');
      expect(json.cards?.length).toBeGreaterThan(0);
    }, 120000);

    it('2.2 选中第1件商品加入购物车：指代消解加入购物车', async () => {
      const req = new NextRequest('http://localhost:3005/api/store/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: '把第1件加入购物车',
          userId: ecomUserId,
          threadId,
          businessId: tenantId,
        }),
      });

      const res = await postStoreChatRoute(req);
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(json.output).toContain('加入购物车');
      expect(json.cards?.length).toBeGreaterThan(0);
    }, 120000);

    it('2.3 选中第2件商品加入购物车：累加商品至购物车', async () => {
      const req = new NextRequest('http://localhost:3005/api/store/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: '把第2件加入购物车',
          userId: ecomUserId,
          threadId,
          businessId: tenantId,
        }),
      });

      const res = await postStoreChatRoute(req);
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(json.output).toContain('加入购物车');
      expect(json.output).toContain('共有 2 件商品');
    }, 120000);

    it('2.4 更改数量：把商品数量修改为 3 件', async () => {
      const req = new NextRequest('http://localhost:3005/api/store/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: '把数量改成3件',
          userId: ecomUserId,
          threadId,
          businessId: tenantId,
        }),
      });

      const res = await postStoreChatRoute(req);
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(json.output).toContain('3 件');
    }, 120000);

    it('2.5 删除商品：将第1件商品从购物车中移除', async () => {
      const req = new NextRequest('http://localhost:3005/api/store/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: '把第1件删除',
          userId: ecomUserId,
          threadId,
          businessId: tenantId,
        }),
      });

      const res = await postStoreChatRoute(req);
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(json.output).toContain('移除');
    }, 120000);

    it('2.6 去结算：查看购物车总价并获取结算预估卡片与优惠金额', async () => {
      const req = new NextRequest('http://localhost:3005/api/store/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: '去结算，看下购物车总价',
          userId: ecomUserId,
          threadId,
          businessId: tenantId,
        }),
      });

      const res = await postStoreChatRoute(req);
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(json.output).toContain('实付预估');
      expect(json.cards?.length).toBeGreaterThan(0);
      expect(json.cards[0].type).toBe('cart_card');
      expect(json.cards[0].data?.actionType).toBe('view');
    }, 120000);
  });

  // =========================================================================
  // 流程 3: 地址簿管理与订单改地址 SOP 规则
  // =========================================================================
  describe('【流程三】地址簿管理 ➔ 未发货订单改地址 ➔ 已发货订单改地址 SOP 拦截', () => {
    const threadId = `merchant_journey_address_${Date.now()}`;
    const targetPaidOrderId = 'AURORA-ORD-2026-9081'; // 待发货/可修改
    const targetShippedOrderId = 'AURORA-ORD-2026-9082'; // 已发货

    it('3.1 地址簿管理：通过 API 获取及保存新收货地址', async () => {
      const saveRes = await MerchantDomainService.saveCustomerAddress(testUserId, {
        recipientName: '张伟 (新地址)',
        phone: '13812345678',
        province: '北京市',
        city: '北京市',
        district: '海淀区',
        detailAddress: '中关村南大街1号院创新大厦B座901',
        isDefault: true,
      });

      expect(saveRes.success).toBe(true);
      expect(saveRes.address?.id).toBeDefined();

      const addresses = await MerchantDomainService.getCustomerAddresses(testUserId);
      expect(addresses.length).toBeGreaterThanOrEqual(1);
      const defaultAddr = addresses.find((a) => a.isDefault);
      expect(defaultAddr?.fullAddress).toContain('中关村南大街1号院');
    });

    it('3.2 未发货订单修改地址：SOP 校验通过并成功变更收货地址', async () => {
      const newAddress = '北京市海淀区中关村南大街1号院创新大厦B座901';
      const req = new NextRequest('http://localhost:3005/api/store/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: `帮我把订单 ${targetPaidOrderId} 的地址修改为 ${newAddress}`,
          userId: testUserId,
          threadId,
          businessId: tenantId,
        }),
      });

      const res = await postStoreChatRoute(req);
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(json.output).toContain('成功');
      expect(json.output).toContain(targetPaidOrderId);
    }, 120000);

    it('3.3 已发货订单修改地址：SOP 校验拦截，提示包裹已发货并建议联系快递派送员', async () => {
      const req = new NextRequest('http://localhost:3005/api/store/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: `帮我把订单 ${targetShippedOrderId} 的地址修改为 上海市浦东新区张江高科园区1号`,
          userId: testUserId,
          threadId,
          businessId: tenantId,
        }),
      });

      const res = await postStoreChatRoute(req);
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      // 校验拦截话术
      expect(json.output).toMatch(/已发货|已发出|无法直接|派件快递员|派送员/);
    }, 120000);
  });
});
