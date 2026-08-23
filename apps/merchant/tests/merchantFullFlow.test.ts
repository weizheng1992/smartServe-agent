import { afterAll, beforeAll, describe, expect, it } from 'bun:test';
import { TenantRegistryService } from 'business-configs';
import { getPgPool } from 'db';
import { NextRequest } from 'next/server';
import { HmacSigner } from 'tools';
import { SkillRegistry } from '../../../packages/engine/src/skills';
import { GET as getAdminOrdersRoute } from '../app/api/admin/orders/route';
import { GET as getStoreProductsRoute } from '../app/api/store/products/route';
import { POST as postOrderActionRoute } from '../app/spi/v1/orders/action/route';
import { GET as getOrderDetailRoute } from '../app/spi/v1/orders/detail/route';
import { GET as getOrdersListRoute } from '../app/spi/v1/orders/list/route';
import { GET as searchProductsRoute } from '../app/spi/v1/products/search/route';
import { GET as getUserInfoRoute } from '../app/spi/v1/user/info/route';
import { seedMerchantData } from '../src/db/seed';
import { MerchantDomainService } from '../src/services/merchantDomainService';

describe('🛍️ Merchant System End-to-End Full Flow (商城/后台/SPI/AI调度)', () => {
  const TEST_PORT = 3009;
  const BASE_URL = `http://localhost:${TEST_PORT}`;
  const SECRET = 'aurora_secret_key_8899';
  const TEST_USER = 'CUST-8801';
  process.env.SPI_BASE_URL_OVERRIDE = BASE_URL;

  let localHttpServer: ReturnType<typeof Bun.serve> | null = null;

  beforeAll(async () => {
    // 1. 初始化商户独立数据库与多规格种子数据
    await seedMerchantData();

    // 2. 启动测试专用 HTTP 调度器
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

  describe('1. 商户独立数据库与领域业务链路 (Merchant Domain Service)', () => {
    let createdOrderId = '';

    it('1.1 应该能正确查询商品列表并包含有效库存与价格', async () => {
      const products = await MerchantDomainService.searchProducts();
      expect(Array.isArray(products)).toBe(true);
      expect(products.length).toBeGreaterThanOrEqual(4);
      expect(products[0].productId).toBeDefined();
      expect(Number(products[0].price)).toBeGreaterThan(0);
      expect(products[0].stock).toBeGreaterThanOrEqual(0);
    });

    it('1.2 应该能成功为顾客模拟下单并扣减库存与生成关联订单明细', async () => {
      const initialProducts = await MerchantDomainService.searchProducts({
        query: '冲锋衣',
      });
      const initialStock = initialProducts[0]?.stock || 0;

      const placeRes = await MerchantDomainService.placeOrder({
        customerId: TEST_USER,
        skuCode: 'AURORA-SKU-002',
        quantity: 1,
        shippingAddress: '北京市海淀区中关村南大街1号院8号楼1201室',
        recipientName: '张伟',
        recipientPhone: '13800138000',
      });

      expect(placeRes.success).toBe(true);
      expect(placeRes.orderId).toBeDefined();
      createdOrderId = placeRes.orderId!;

      // 验证库存已扣减
      const afterProducts = await MerchantDomainService.searchProducts({
        query: '冲锋衣',
      });
      expect(afterProducts[0]?.stock).toBe(initialStock - 1);

      // 验证订单已物理落盘
      const order = await MerchantDomainService.getOrderDetail(createdOrderId);
      expect(order).not.toBeNull();
      expect(order?.status).toBe('PAID');
      expect(order?.isAddressModifiable).toBe(true);
      expect(order?.items.length).toBe(1);
      expect(order?.items[0].skuId).toBe('AURORA-SKU-002');
    });

    it('1.3 应该支持在未发货前修改收货地址并记录审计流水', async () => {
      const newAddress = '北京市朝阳区望京SOHO T1座 1508室 (全流程测试)';
      const idempotencyKey = `IDEM_ADDR_${Date.now()}`;

      const actionRes = await MerchantDomainService.executeOrderAction({
        actionType: 'MODIFY_ADDRESS',
        orderId: createdOrderId,
        newAddress,
        idempotencyKey,
      });

      expect(actionRes.success).toBe(true);
      expect(actionRes.updatedAddress).toBe(newAddress);

      // 校验订单地址已实时更新
      const updatedOrder = await MerchantDomainService.getOrderDetail(createdOrderId);
      expect(updatedOrder?.shippingAddress.fullAddress).toBe(newAddress);

      // 校验幂等性防重调用
      const repeatRes = await MerchantDomainService.executeOrderAction({
        actionType: 'MODIFY_ADDRESS',
        orderId: createdOrderId,
        newAddress,
        idempotencyKey,
      });
      expect(repeatRes.success).toBe(true);
      expect(repeatRes.message).toContain('幂等防重响应');
    });

    it('1.4 商户后台发货后应流转状态为已发货并禁止再修改地址', async () => {
      const shipRes = await MerchantDomainService.shipOrder({
        orderId: createdOrderId,
        carrierCode: 'SF',
        trackingNo: `SF_TEST_${Date.now()}`,
      });

      expect(shipRes.success).toBe(true);

      // 校验订单状态
      const shippedOrder = await MerchantDomainService.getOrderDetail(createdOrderId);
      expect(shippedOrder?.status).toBe('SHIPPED');
      expect(shippedOrder?.isAddressModifiable).toBe(false);

      // 再次尝试修改地址应该被物理拦截
      const modifyAfterShip = await MerchantDomainService.executeOrderAction({
        actionType: 'MODIFY_ADDRESS',
        orderId: createdOrderId,
        newAddress: '北京市东城区王府井大街1号',
        idempotencyKey: `IDEM_FAIL_${Date.now()}`,
      });
      expect(modifyAfterShip.success).toBe(false);
      expect(modifyAfterShip.message).toContain('禁止修改地址');
    });
  });

  describe('2. HTTP SPI 开放接口与 HMAC 签名鉴权 (Port 3005 REST Endpoints)', () => {
    it('2.1 GET /spi/v1/user/info 应返回标准格式顾客信息与地址簿', async () => {
      const res = await fetch(`${BASE_URL}/spi/v1/user/info?userId=${TEST_USER}`);
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(json.data.userId).toBe(TEST_USER);
      expect(json.data.name).toBe('张伟');
      expect(Array.isArray(json.data.addresses)).toBe(true);
    });

    it('2.2 GET /spi/v1/orders/list 应返回顾客最新订单列表', async () => {
      const res = await fetch(`${BASE_URL}/spi/v1/orders/list?userId=${TEST_USER}`);
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(Array.isArray(json.data)).toBe(true);
      expect(json.data.length).toBeGreaterThan(0);
    });

    it('2.3 GET /spi/v1/products/search 应返回现货商品目录', async () => {
      const res = await fetch(`${BASE_URL}/spi/v1/products/search?query=T恤`);
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(Array.isArray(json.data)).toBe(true);
      expect(json.data.some((p: any) => p.title.includes('T恤'))).toBe(true);
    });

    it('2.4 POST /spi/v1/orders/action 携带未签名或篡改签名的请求应被 401 拦截', async () => {
      const body = JSON.stringify({
        orderId: 'AURORA-ORD-2026-9081',
        actionType: 'MODIFY_ADDRESS',
        newAddress: '非法请求测试',
      });

      // 未携带签名请求
      const resNoSign = await fetch(`${BASE_URL}/spi/v1/orders/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
      });
      expect(resNoSign.status).toBe(401);

      // 携带错误签名
      const resBadSign = await fetch(`${BASE_URL}/spi/v1/orders/action`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Tenant-Id': 'aurora',
          'X-Timestamp': String(Date.now()),
          'X-Nonce': 'nonce-test',
          'X-Signature': 'invalid_signature_hex_000000000000000000000000000000000000000000000000',
        },
        body,
      });
      expect(resBadSign.status).toBe(401);
    });

    it('2.5 POST /spi/v1/orders/action 携带合法 HMAC-SHA256 签名应执行成功', async () => {
      const timestamp = Date.now();
      const nonce = `test_nonce_${Math.random()}`;
      const payloadObj = {
        orderId: 'AURORA-ORD-2026-9081',
        actionType: 'MODIFY_ADDRESS',
        newAddress: '北京市西城区金融大街甲9号金融街中心',
        idempotencyKey: `SPI_TEST_${Date.now()}`,
      };
      const bodyStr = JSON.stringify(payloadObj);

      const signature = HmacSigner.sign({
        method: 'POST',
        path: '/spi/v1/orders/action',
        timestamp,
        nonce,
        body: bodyStr,
        secret: SECRET,
      });

      const res = await fetch(`${BASE_URL}/spi/v1/orders/action`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Tenant-Id': 'aurora',
          'X-Timestamp': String(timestamp),
          'X-Nonce': nonce,
          'X-Signature': signature,
          'X-Idempotency-Key': payloadObj.idempotencyKey,
        },
        body: bodyStr,
      });

      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(json.data.actionType).toBe('MODIFY_ADDRESS');
      expect(json.data.updatedAddress).toBe(payloadObj.newAddress);
    });
  });

  describe('3. AI 智能体 Skill SOP 分发与端到端穿透调度', () => {
    it('3.1 极速改地址 SOP 应通过 SPI 自动鉴权调度远端商户并返回 RichCard', async () => {
      const skill = SkillRegistry.getSkill('skill_order_address_modification');
      expect(skill).toBeDefined();

      const context = {
        threadId: `thread_${Date.now()}`,
        tenantId: 'aurora', // 动态命中远程 SPI
        userId: TEST_USER,
        input: '请帮我修改订单地址为：北京市朝阳区三里屯太古里北区N8座',
        slots: {
          orderId: 'AURORA-ORD-2026-9081',
          newAddress: '北京市朝阳区三里屯太古里北区N8座',
        },
      };

      const result = await skill!.execute(context);
      expect(result.success).toBe(true);
      expect(result.output).toContain('AURORA-ORD-2026-9081');
      expect(result.output).toContain('收货地址变更为');
      expect(Array.isArray(result.cards)).toBe(true);
      expect(result.cards?.[0].type).toBe('order_card');
    });

    it('3.2 现货导购 SOP 应穿透商户库存查询商品并生成自然语言推荐', async () => {
      const skill = SkillRegistry.getSkill('skill_product_inquiry');
      expect(skill).toBeDefined();

      const result = await skill!.execute({
        threadId: `thread_${Date.now()}`,
        tenantId: 'aurora',
        input: '店里有工装裤吗？多少钱？',
        slots: {
          query: '工装裤',
        },
      });

      expect(result.success).toBe(true);
      expect(result.output).toContain('工装裤');
      expect(result.output).toContain('¥');
    });
  });

  describe('4. 商户前台与管理后台 REST API 接口验证', () => {
    it('4.1 GET /api/store/products 应输出前台商品', async () => {
      const res = await fetch(`${BASE_URL}/api/store/products`);
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(json.products.length).toBeGreaterThan(0);
    });

    it('4.2 GET /api/admin/orders 应输出订单列表、审计日志和库存汇总', async () => {
      const res = await fetch(`${BASE_URL}/api/admin/orders`);
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(Array.isArray(json.orders)).toBe(true);
      expect(Array.isArray(json.auditLogs)).toBe(true);
      expect(Array.isArray(json.inventory)).toBe(true);
    });
  });
});
