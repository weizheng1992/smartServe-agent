import { afterAll, beforeAll, describe, expect, it } from "bun:test";
import { NextRequest } from "next/server";
import {
  GET as getAddressesRoute,
  POST as postAddressesRoute,
} from "../app/api/store/addresses/route";
import { GET as getOrderDetailRoute } from "../app/api/store/orders/[id]/route";
import {
  GET as getOrdersRoute,
  POST as postOrdersRoute,
} from "../app/api/store/orders/route";
import { seedMerchantData } from "../src/db/seed";
import { MerchantDomainService } from "../src/services/merchantDomainService";

describe("🛍️ Merchant Storefront E-Commerce Complete Flow (Cart / Orders / Address / Tracking)", () => {
  const TEST_USER = "CUST-8801";

  beforeAll(async () => {
    await seedMerchantData();
  });

  describe("1. 地址簿管理与默认地址设定 (Address Management)", () => {
    it("1.1 应该能获取当前顾客的多条收货地址", async () => {
      const addresses =
        await MerchantDomainService.getCustomerAddresses(TEST_USER);
      expect(Array.isArray(addresses)).toBe(true);
      expect(addresses.length).toBeGreaterThanOrEqual(1);
      expect(addresses[0].recipientName).toBe("张伟");
      expect(addresses[0].isDefault).toBe(true);
    });

    it("1.2 应该能新增一条收货地址并支持设为默认地址", async () => {
      const newAddr = {
        recipientName: "张伟 (公司)",
        phone: "13911112222",
        province: "上海市",
        city: "上海市",
        district: "浦东新区",
        detailAddress: "陆家嘴环路1000号恒生银行大厦28楼",
        isDefault: true,
      };

      const result = await MerchantDomainService.saveCustomerAddress(
        TEST_USER,
        newAddr,
      );
      expect(result.success).toBe(true);
      expect(result.address?.id).toBeDefined();

      // 验证新增后并重新读取地址列表
      const updatedList =
        await MerchantDomainService.getCustomerAddresses(TEST_USER);
      expect(updatedList.length).toBeGreaterThanOrEqual(2);
      const defaultAddr = updatedList.find((a) => a.isDefault);
      expect(defaultAddr?.recipientName).toBe("张伟 (公司)");
      expect(defaultAddr?.fullAddress).toContain("陆家嘴环路1000号");
    });

    it("1.3 通过 HTTP API GET & POST /api/store/addresses 操作地址簿", async () => {
      // 1. GET 请求
      const getReq = new NextRequest(
        `http://localhost:3005/api/store/addresses?userId=${TEST_USER}`,
      );
      const getRes = await getAddressesRoute(getReq);
      expect(getRes.status).toBe(200);
      const getJson = await getRes.json();
      expect(getJson.success).toBe(true);
      expect(Array.isArray(getJson.addresses)).toBe(true);

      // 2. POST 新增请求
      const postReq = new NextRequest(
        "http://localhost:3005/api/store/addresses",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            userId: TEST_USER,
            recipientName: "李雷",
            phone: "13888889999",
            fullAddress: "深圳市南山区高新南九道9号",
            isDefault: false,
          }),
        },
      );
      const postRes = await postAddressesRoute(postReq);
      expect(postRes.status).toBe(200);
      const postJson = await postRes.json();
      expect(postJson.success).toBe(true);
      expect(postJson.address.recipientName).toBe("李雷");
    });
  });

  describe("2. 购物车批量多商品结算与扣减库存 (Cart Checkout)", () => {
    let createdCartOrderId = "";

    it("2.1 应该支持将多个不同规格商品从购物车批量下单并生成订单明细", async () => {
      const initialProducts = await MerchantDomainService.searchProducts();
      const sku1 = initialProducts[0].skus[0];
      const sku2 = initialProducts[1].skus[0];
      const initialStock1 = sku1.stock;
      const initialStock2 = sku2.stock;

      const cartCheckoutRes = await MerchantDomainService.createOrderFromCart({
        customerId: TEST_USER,
        items: [
          {
            skuCode: sku1.skuCode,
            quantity: 2,
          },
          {
            skuCode: sku2.skuCode,
            quantity: 1,
          },
        ],
        shippingAddress: {
          recipientName: "张伟",
          phone: "13800138000",
          fullAddress: "北京市海淀区中关村南大街1号院8号楼1201室",
        },
      });

      expect(cartCheckoutRes.success).toBe(true);
      expect(cartCheckoutRes.orderId).toBeDefined();
      createdCartOrderId = cartCheckoutRes.orderId!;

      // 验证总价计算正确
      const expectedTotal = Number(sku1.price) * 2 + Number(sku2.price) * 1;
      expect(Number(cartCheckoutRes.totalAmount)).toBeCloseTo(expectedTotal, 2);

      // 验证库存被正确扣减
      const afterProducts = await MerchantDomainService.searchProducts();
      const updatedSku1 = afterProducts[0].skus.find(
        (s) => s.skuCode === sku1.skuCode,
      );
      const updatedSku2 = afterProducts[1].skus.find(
        (s) => s.skuCode === sku2.skuCode,
      );
      expect(updatedSku1?.stock).toBe(initialStock1 - 2);
      expect(updatedSku2?.stock).toBe(initialStock2 - 1);
    });

    it("2.2 通过 HTTP API POST /api/store/orders 支持购物车合并下单", async () => {
      const products = await MerchantDomainService.searchProducts();
      const sku = products[0].skus[0];

      const postReq = new NextRequest(
        "http://localhost:3005/api/store/orders",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            customerId: TEST_USER,
            items: [
              {
                skuCode: sku.skuCode,
                quantity: 1,
              },
            ],
            shippingAddress: "北京市朝阳区三里屯太古里北区",
            recipientName: "张伟",
            recipientPhone: "13800138000",
          }),
        },
      );

      const res = await postOrdersRoute(postReq);
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(json.orderId).toBeDefined();
    });
  });

  describe("3. 订单详情、多状态检索与可视化物流轨迹 (Order Detail & Tracking)", () => {
    let shippedOrderId = "";

    beforeAll(async () => {
      // 下单并标记为发货以生成真实物流轨迹
      const order = await MerchantDomainService.placeOrder({
        customerId: TEST_USER,
        skuCode: "AURORA-SKU-002",
        quantity: 1,
        shippingAddress: "北京市海淀区中关村南大街1号院",
        recipientName: "张伟",
        recipientPhone: "13800138000",
      });
      shippedOrderId = order.orderId!;

      await MerchantDomainService.shipOrder({
        orderId: shippedOrderId,
        carrierCode: "SF",
        trackingNo: `SF_TRACK_${Date.now()}`,
      });
    });

    it("3.1 应该能通过 GET /api/store/orders 按状态过滤订单", async () => {
      const req = new NextRequest(
        `http://localhost:3005/api/store/orders?userId=${TEST_USER}&status=SHIPPED`,
      );
      const res = await getOrdersRoute(req);
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(Array.isArray(json.orders)).toBe(true);
      expect(json.orders.every((o: any) => o.status === "SHIPPED")).toBe(true);
    });

    it("3.2 应该能通过 GET /api/store/orders/[id] 拉取完整订单详情与物流节点时间线", async () => {
      const req = new NextRequest(
        `http://localhost:3005/api/store/orders/${shippedOrderId}`,
      );
      const res = await getOrderDetailRoute(req, {
        params: Promise.resolve({ id: shippedOrderId }),
      });
      expect(res.status).toBe(200);
      const json = await res.json();
      expect(json.success).toBe(true);
      expect(json.order).toBeDefined();
      expect(json.order.orderId).toBe(shippedOrderId);
      expect(json.order.status).toBe("SHIPPED");

      // 验证物流动态时间线
      expect(json.order.tracking).toBeDefined();
      expect(json.order.tracking.carrier).toBeDefined();
      expect(json.order.tracking.trackingNumber).toBeDefined();
      expect(Array.isArray(json.order.tracking.timeline)).toBe(true);
      expect(json.order.tracking.timeline.length).toBeGreaterThanOrEqual(3);
      expect(json.order.tracking.timeline[0].status).toBeDefined();
      expect(json.order.tracking.timeline[0].time).toBeDefined();
    });
  });
});
