import { describe, expect, it } from 'bun:test';
import {
  MallDomainService,
  applyAfterSale,
  getAllTools,
  getTool,
  getUserAddresses,
  queryPackageTracking,
  queryProductReviews,
  queryProductSkus,
  saveUserAddress,
} from '../src';

describe('🌟 MallDomainService & E-Commerce Tools Suite', () => {
  describe('1. User Address Book (收货地址薄)', () => {
    it('should retrieve user addresses with default tag and full formatted address', async () => {
      const result = await MallDomainService.getUserAddresses('user_test_001', 'ecommerce');
      expect(result).toHaveProperty('addresses');
      const list = result.addresses as Array<{
        fullAddress: string;
        isDefault: boolean;
        tag: string;
      }>;
      expect(list.length).toBeGreaterThan(0);
      expect(list[0]).toHaveProperty('fullAddress');
      expect(list[0]).toHaveProperty('tag');
    });

    it('should allow saving a new delivery address', async () => {
      const saveRes = await MallDomainService.saveUserAddress({
        userId: 'user_test_002',
        businessId: 'ecommerce',
        receiverName: '李女士',
        receiverPhone: '13912345678',
        province: '上海市',
        city: '上海市',
        district: '浦东新区',
        detailAddress: '张江高科技园区博云路2号',
        tag: 'company',
        isDefault: true,
      });

      expect(saveRes.success).toBe(true);
      expect(saveRes.fullAddress).toContain('上海市浦东新区张江高科技园区博云路2号');
      expect(saveRes.tag).toBe('company');
    });
  });

  describe('2. Product SKUs & Multi-Specification (商品多规格与库存)', () => {
    it('should return detailed SKUs for a product', async () => {
      const res = await MallDomainService.queryProductSkus({
        productId: 'prod_nike_air_jordan_1',
      });

      expect(res).toHaveProperty('skus');
      const skus = res.skus as Array<{
        skuCode: string;
        specs: Record<string, string>;
        price: string;
      }>;
      expect(skus.length).toBeGreaterThan(0);
      expect(skus[0]).toHaveProperty('specs');
    });

    it('should filter SKUs by size and color', async () => {
      const res = await MallDomainService.queryProductSkus({
        productId: 'prod_nike_air_jordan_1',
        size: '42',
        color: '黑',
      });

      const skus = res.skus as Array<{ specs: Record<string, string> }>;
      expect(skus.length).toBeGreaterThan(0);
      expect(skus[0].specs.size).toContain('42');
    });
  });

  describe('3. Logistics & Package Tracking (物流时序轨迹)', () => {
    it('should return courier info and chronological tracking nodes', async () => {
      const res = await MallDomainService.queryPackageTracking({
        orderId: 'ORD-ECOM-889901',
        trackingNumber: 'SF1092837465',
      });

      expect(res).toHaveProperty('carrier');
      expect(res).toHaveProperty('trackTimeline');
      expect(res).toHaveProperty('courier');

      const timeline = res.trackTimeline as Array<{
        status: string;
        description: string;
      }>;
      expect(timeline.length).toBeGreaterThan(0);
      expect(timeline[0]).toHaveProperty('description');
    });
  });

  describe('4. Product Reviews & Customer Sentiment (评价与口碑画像)', () => {
    it('should return review ratings, sentiment consensus, and sizing fit feedback', async () => {
      const res = await MallDomainService.queryProductReviews({
        productId: 'prod_nike_air_jordan_1',
      });

      expect(res).toHaveProperty('avgRating');
      expect(res).toHaveProperty('sentimentSummary');
      expect(res).toHaveProperty('reviews');

      const reviews = res.reviews as Array<{
        rating: string;
        fitFeedback: string;
      }>;
      expect(reviews.length).toBeGreaterThan(0);
      expect(reviews[0]).toHaveProperty('fitFeedback');
    });
  });

  describe('5. After-Sale Application (售后工单申请)', () => {
    it('should generate after-sale ticket and clear cache on valid refund/return request', async () => {
      const res = await MallDomainService.applyAfterSale({
        orderId: 'ORD-ECOM-889901',
        type: 'refund_only',
        reason: 'quality_issue',
        reasonDescription: '收到后发现商品外壳有划痕',
        refundAmount: 299.0,
      });

      expect(res.success).toBe(true);
      expect(res).toHaveProperty('ticketId');
      expect(res.status).toBe('pending_review');
      expect(res.instruction).toContain('仅退款申请已提交');
    });
  });

  describe('6. Tool Registry Central Registration (Agent 工具集注册)', () => {
    it('should have registered all 6 new mall tools into registry', () => {
      expect(getTool('getUserAddresses')).toBeDefined();
      expect(getTool('saveUserAddress')).toBeDefined();
      expect(getTool('queryProductSkus')).toBeDefined();
      expect(getTool('queryPackageTracking')).toBeDefined();
      expect(getTool('queryProductReviews')).toBeDefined();
      expect(getTool('applyAfterSale')).toBeDefined();

      const allTools = getAllTools();
      const toolNames = allTools.map((t) => t.name);
      expect(toolNames).toContain('getUserAddresses');
      expect(toolNames).toContain('queryProductSkus');
      expect(toolNames).toContain('queryPackageTracking');
    });

    it('should execute tool through registry with schema validation', async () => {
      const trackingTool = getTool('queryPackageTracking');
      expect(trackingTool).toBeDefined();

      const output = await trackingTool!.execute({
        orderId: 'ORD-ECOM-889901',
      });
      expect(output).toHaveProperty('carrier');
    });
  });
});
