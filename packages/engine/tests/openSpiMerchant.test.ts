import { afterAll, beforeAll, describe, expect, it } from 'bun:test';
import { TenantRegistryService } from 'business-configs';
import { HmacSigner } from 'tools';
import { seedMerchantData } from '../../../apps/merchant/src/db/seed';
import { MerchantDomainService } from '../../../apps/merchant/src/services/merchantDomainService';
import { SkillRegistry } from '../src/skills';

describe('Open Merchant Integration Architecture (SPI & Skills)', () => {
  const TEST_SECRET = 'aurora_secret_key_8899';
  const TEST_PORT = 3009;
  process.env.SPI_BASE_URL_OVERRIDE = `http://localhost:${TEST_PORT}`;
  let mockServer: any;

  beforeAll(async () => {
    // 0. 初始化商户独立数据库种子数据
    await seedMerchantData();

    // 启动测试专用 SPI 调度服务
    mockServer = Bun.serve({
      port: TEST_PORT,
      async fetch(req) {
        const url = new URL(req.url);
        if (url.pathname === '/spi/v1/user/info') {
          const userId = url.searchParams.get('userId') || undefined;
          const user = await MerchantDomainService.getUserInfo({
            userId,
          });
          return Response.json({ success: true, data: user });
        }
        if (url.pathname === '/spi/v1/orders/list') {
          const userId = url.searchParams.get('userId') || undefined;
          const orders = await MerchantDomainService.listOrders({
            userId,
          });
          return Response.json({ success: true, data: orders });
        }
        if (url.pathname === '/spi/v1/orders/detail') {
          const orderId = url.searchParams.get('orderId') || '';
          const order = await MerchantDomainService.getOrderDetail(orderId);
          return Response.json({ success: true, data: order });
        }
        if (url.pathname === '/spi/v1/orders/action') {
          const body = await req.json();
          const signature = req.headers.get('x-signature') || '';
          const res = await MerchantDomainService.executeOrderAction(body, signature);
          return Response.json({ success: res.success, data: res });
        }
        if (url.pathname === '/spi/v1/products/search') {
          const query = url.searchParams.get('query') || undefined;
          const products = await MerchantDomainService.searchProducts({
            query,
          });
          return Response.json({ success: true, data: products });
        }
        return Response.json({ success: true });
      },
    });
  });

  afterAll(() => {
    mockServer?.stop();
    delete process.env.SPI_BASE_URL_OVERRIDE;
  });

  describe('1. HMAC-SHA256 Signer & Verification', () => {
    it('should generate valid HMAC signature and verify successfully', () => {
      const timestamp = Date.now();
      const nonce = 'random-nonce-12345';
      const body = JSON.stringify({
        orderId: 'AURORA-ORD-2026-9081',
        actionType: 'MODIFY_ADDRESS',
      });

      const signature = HmacSigner.sign({
        method: 'POST',
        path: '/spi/v1/orders/action',
        timestamp,
        nonce,
        body,
        secret: TEST_SECRET,
      });

      expect(signature).toBeDefined();
      expect(typeof signature).toBe('string');
      expect(signature.length).toBe(64); // sha256 hex string

      const isValid = HmacSigner.verify({
        method: 'POST',
        path: '/spi/v1/orders/action',
        timestamp,
        nonce,
        body,
        secret: TEST_SECRET,
        signature,
      });

      expect(isValid).toBe(true);
    });

    it('should reject tampered payload with invalid signature', () => {
      const timestamp = Date.now();
      const nonce = 'random-nonce-12345';
      const body = JSON.stringify({
        orderId: 'AURORA-ORD-2026-9081',
        amount: 100,
      });

      const signature = HmacSigner.sign({
        method: 'POST',
        path: '/spi/v1/orders/action',
        timestamp,
        nonce,
        body,
        secret: TEST_SECRET,
      });

      const isValid = HmacSigner.verify({
        method: 'POST',
        path: '/spi/v1/orders/action',
        timestamp,
        nonce,
        body: JSON.stringify({ orderId: 'AURORA-ORD-2026-9081', amount: 9999 }), // tampered
        secret: TEST_SECRET,
        signature,
      });

      expect(isValid).toBe(false);
    });
  });

  describe('2. Merchant Domain Service (Independent Third-Party DB)', () => {
    it('should fetch third-party customer info and address book', async () => {
      const customer = await MerchantDomainService.getUserInfo({
        userId: 'CUST-8801',
      });
      expect(customer).not.toBeNull();
      expect(customer?.userId).toBe('CUST-8801');
      expect(customer?.name).toBe('张伟');
      expect(customer?.memberLevel).toBeDefined();
      expect(Array.isArray(customer?.addresses)).toBe(true);
      expect(customer?.addresses?.length).toBeGreaterThan(0);
    });

    it('should query on-sale products from third_party_inventory', async () => {
      const products = await MerchantDomainService.searchProducts({
        limit: 10,
      });
      expect(Array.isArray(products)).toBe(true);
      expect(products.length).toBeGreaterThanOrEqual(4);
      expect(products[0].productId).toBeDefined();
      expect(products[0].title).toBeDefined();
      expect(products[0].price).toBeGreaterThan(0);
    });

    it('should list customer orders and check order detail', async () => {
      const orders = await MerchantDomainService.listOrders({
        userId: 'CUST-8801',
      });
      expect(Array.isArray(orders)).toBe(true);
      expect(orders.length).toBeGreaterThanOrEqual(2);

      const orderDetail = await MerchantDomainService.getOrderDetail(orders[0].orderId);
      expect(orderDetail).not.toBeNull();
      expect(orderDetail?.orderId).toBe(orders[0].orderId);
      expect(orderDetail?.items.length).toBeGreaterThan(0);
    });

    it('should handle order action with idempotency protection', async () => {
      const idempotencyKey = `TEST_IDEMPOTENCY_${Date.now()}`;
      const newAddr = '北京市海淀区中关村南大街1号院8号楼1201室 (测试修改)';

      // 第一次调用
      const res1 = await MerchantDomainService.executeOrderAction({
        actionType: 'MODIFY_ADDRESS',
        orderId: 'AURORA-ORD-2026-9081',
        newAddress: newAddr,
        idempotencyKey,
      });

      expect(res1.success).toBe(true);
      expect(res1.actionType).toBe('MODIFY_ADDRESS');

      // 第二次携带相同幂等 Key 调用，应命中幂等防重返回
      const res2 = await MerchantDomainService.executeOrderAction({
        actionType: 'MODIFY_ADDRESS',
        orderId: 'AURORA-ORD-2026-9081',
        newAddress: newAddr,
        idempotencyKey,
      });

      expect(res2.success).toBe(true);
      expect(res2.message).toContain('幂等防重响应');
    });

    it('should reject address modification for shipped orders', async () => {
      const res = await MerchantDomainService.executeOrderAction({
        actionType: 'MODIFY_ADDRESS',
        orderId: 'AURORA-ORD-2026-9082', // 已发货订单
        newAddress: '北京市西城区金融街1号',
        idempotencyKey: `TEST_SHIPPED_${Date.now()}`,
      });

      expect(res.success).toBe(false);
      expect(res.message).toContain('禁止修改地址');
    });
  });

  describe('3. Dynamic Tenant Registry (DB-Driven Zero Hardcode)', () => {
    it('should dynamically load aurora tenant from database', async () => {
      const tenantConfig = await TenantRegistryService.getTenantConfig('aurora');
      expect(tenantConfig).toBeDefined();
      expect(tenantConfig.businessId).toBe('aurora');
      expect(tenantConfig.name).toBe('极光潮品官方旗舰店');
      expect(tenantConfig.spiConnector?.mode).toBe('remote_spi');
      expect(tenantConfig.spiConnector?.spiBaseUrl).toBe(process.env.SPI_BASE_URL_OVERRIDE || 'http://localhost:3005');
    });

    it('should resolve dynamic display name without hardcoded if-else', async () => {
      const name = await TenantRegistryService.getMerchantDisplayName('aurora');
      expect(name).toBe('极光潮品官方旗舰店');
    });
  });

  describe('4. Skill Registry & Execution Layer (Remote SPI E2E Dispatch)', () => {
    it('should find matching skill for address modification', () => {
      const skill = SkillRegistry.findMatchingSkill({
        threadId: 't_test_1',
        tenantId: 'aurora',
        input: '修改地址',
        slots: { activeIntent: 'ORDER_MODIFY_ADDRESS' },
      });

      expect(skill).not.toBeNull();
      expect(skill?.metadata.id).toBe('skill_order_address_modification');
    });

    it('should execute OrderAddressModificationSkill via remote SPI and return rich card', async () => {
      const skill = SkillRegistry.getSkill('skill_order_address_modification');
      expect(skill).toBeDefined();

      const result = await skill!.execute({
        threadId: 't_test_addr',
        tenantId: 'aurora', // automatically calls port 3005 remote SPI with HMAC signature!
        userId: 'CUST-8801',
        input: '修改地址',
        slots: {
          orderId: 'AURORA-ORD-2026-9081',
          newAddress: '北京市海淀区中关村南大街1号院8号楼1201室',
        },
      });

      expect(result.skillId).toBe('skill_order_address_modification');
      expect(result.success).toBe(true);
      expect(result.cards?.length).toBeGreaterThan(0);
      expect(result.cards?.[0].type).toBe('order_card');
    });

    it('should execute ProductInquirySkill via remote SPI and return recommendations', async () => {
      const skill = SkillRegistry.getSkill('skill_product_inquiry');
      expect(skill).toBeDefined();

      const result = await skill!.execute({
        threadId: 't_test_prod',
        tenantId: 'aurora',
        input: '推荐冲锋衣',
        slots: {
          query: '冲锋衣',
        },
      });

      expect(result.skillId).toBe('skill_product_inquiry');
      expect(result.success).toBe(true);
      expect(result.output).toContain('相关商品');
      expect(result.output).toContain('冲锋衣');
    });
  });
});
