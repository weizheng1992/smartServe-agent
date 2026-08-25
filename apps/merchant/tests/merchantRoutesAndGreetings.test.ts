import { describe, expect, it } from "bun:test";
import { NextRequest } from "next/server";
import { POST as postChatRoute } from "../app/api/store/chat/route";
import { GET as getOrderDetailRoute } from "../app/api/store/orders/[id]/route";
import {
  GET as getOrdersRoute,
  POST as postOrdersRoute,
} from "../app/api/store/orders/route";
import { GET as getProductDetailRoute } from "../app/api/store/products/[id]/route";
import { GET as getProductsRoute } from "../app/api/store/products/route";
import { getGreetingForRoute } from "../app/components/chat/routeGreetingConfig";

describe("🛍️ Merchant Route Pages & Route-Aware Greetings Suite", () => {
  it("1. 应该能根据不同路由与页面上下文生成定制化 AI 问候语", () => {
    // 首页问候语
    const homeGreeting = getGreetingForRoute({
      pathname: "/",
    });
    expect(homeGreeting).toContain("极光潮品官方智能客服");

    // 商品详情页问候语 (携带商品标题)
    const productGreeting = getGreetingForRoute({
      pathname: "/products/AURORA-SPU-001",
      productTitle: "极光三合一机能硬壳冲锋衣",
      productCategory: "机能外套",
    });
    expect(productGreeting).toContain("极光三合一机能硬壳冲锋衣");
    expect(productGreeting).toContain("机能外套");
    expect(productGreeting).toContain("尺码选择");

    // 购物车页问候语 (有商品)
    const cartGreetingWithItems = getGreetingForRoute({
      pathname: "/cart",
      cartItemCount: 3,
    });
    expect(cartGreetingWithItems).toContain("3 件心仪商品");
    expect(cartGreetingWithItems).toContain("优惠券");

    // 购物车页问候语 (空购物车)
    const emptyCartGreeting = getGreetingForRoute({
      pathname: "/cart",
      cartItemCount: 0,
    });
    expect(emptyCartGreeting).toContain("购物车空空如也");

    // 订单中心页问候语
    const ordersGreeting = getGreetingForRoute({
      pathname: "/orders",
      orderCount: 4,
    });
    expect(ordersGreeting).toContain("4 笔订单记录");
    expect(ordersGreeting).toContain("顺丰物流");

    // 地址簿页问候语
    const addressGreeting = getGreetingForRoute({
      pathname: "/addresses",
      addressCount: 2,
    });
    expect(addressGreeting).toContain("常用收货地址簿");
    expect(addressGreeting).toContain("未发货订单一键同步更新");
  });

  it("2. 应该能通过 /api/store/products/[id] 获取单个 SPU/Product 详情", async () => {
    const listReq = new NextRequest("http://localhost:3005/api/store/products");
    const listRes = await getProductsRoute();
    expect(listRes.status).toBe(200);
    const listJson = await listRes.json();
    expect(listJson.success).toBe(true);
    expect(listJson.products.length).toBeGreaterThan(0);

    const firstProduct = listJson.products[0];
    const targetId = firstProduct.productId || firstProduct.spuId;

    const detailReq = new NextRequest(
      `http://localhost:3005/api/store/products/${targetId}`,
    );
    const detailRes = await getProductDetailRoute(detailReq, {
      params: Promise.resolve({ id: targetId }),
    });

    expect(detailRes.status).toBe(200);
    const detailJson = await detailRes.json();
    expect(detailJson.success).toBe(true);
    expect(detailJson.product).toBeDefined();
    expect(detailJson.product.title).toBe(firstProduct.title);
    expect(Array.isArray(detailJson.product.skus)).toBe(true);
  });

  it("3. 应该能通过 /api/store/orders 支持 customerId/userId 查询与单笔订单详情", async () => {
    // 1. 查询订单列表 (通过 customerId 参数)
    const listReq = new NextRequest(
      "http://localhost:3005/api/store/orders?customerId=CUST-8801",
    );
    const listRes = await getOrdersRoute(listReq);
    expect(listRes.status).toBe(200);
    const listJson = await listRes.json();
    expect(listJson.success).toBe(true);
    expect(Array.isArray(listJson.orders)).toBe(true);

    if (listJson.orders.length > 0) {
      const orderId = listJson.orders[0].orderId;
      const detailReq = new NextRequest(
        `http://localhost:3005/api/store/orders/${orderId}`,
      );
      const detailRes = await getOrderDetailRoute(detailReq, {
        params: Promise.resolve({ id: orderId }),
      });
      expect(detailRes.status).toBe(200);
      const detailJson = await detailRes.json();
      expect(detailJson.success).toBe(true);
      expect(detailJson.order.orderId).toBe(orderId);
    }
  });

  it("4. 应该能通过 /api/store/chat 成功处理用户长文本查询并调起 RAG 与订单技能", async () => {
    const threadId = `merchant_thread_test_rag_${Date.now()}`;
    const chatReq = new NextRequest("http://localhost:3005/api/store/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "查询我的全部订单",
        threadId,
        userId: "CUST-8801",
        businessId: "aurora",
        routeContext: { pathname: "/" },
      }),
    });

    const chatRes = await postChatRoute(chatReq);
    expect(chatRes.status).toBe(200);
    const chatJson = await chatRes.json();
    expect(chatJson.success).toBe(true);
    expect(chatJson.output || chatJson.result).toBeDefined();
  }, 30000);
});
