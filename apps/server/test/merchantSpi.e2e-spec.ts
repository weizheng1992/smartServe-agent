import { afterAll, beforeAll, describe, expect, it } from "bun:test";
import type { INestApplication } from "@nestjs/common";
import { Test, type TestingModule } from "@nestjs/testing";
import { db, getDrizzle, pendingApprovals } from "db";
import { eq } from "drizzle-orm";
import request from "supertest";
import { AppModule } from "../src/app.module";

describe("🌟 Merchant SPI Open Gateway E2E Suite", () => {
  let app: INestApplication;

  beforeAll(async () => {
    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = moduleFixture.createNestApplication();
    await app.init();
  });

  afterAll(async () => {
    await app.close();
  });

  describe("1. POST /api/v1/spi/approvals/:id/resolve", () => {
    it("should allow merchant to resolve pending approval via Open API", async () => {
      const threadId = `spi_app_${Date.now()}`;
      const approvalId = `app_spi_${Date.now()}`;
      const businessId = "nike";

      await db.createThread(threadId, "u_spi_user", businessId);

      const drizzle = getDrizzle();
      if (drizzle) {
        await drizzle.insert(pendingApprovals).values({
          id: approvalId,
          threadId,
          businessId,
          status: "waiting",
          actionType: "processRefund",
          reason: "超额退款待商户核验",
          actionPayload: {
            orderId: "ORD-TEST-999",
            amount: 500,
          },
        });
      }

      // 模拟商户在其自有后台调用平台开放 API 提交决议 (通过)
      const res = await request(app.getHttpServer())
        .post(`/api/v1/spi/approvals/${approvalId}/resolve`)
        .set("x-tenant-id", "nike")
        .set("x-api-key", "key_nike")
        .send({
          action: "approve",
          reviewerId: "nike_manager_01",
        });

      expect(res.status).toBe(200);
      expect(res.body.success).toBe(true);
      expect(res.body.status).toBe("approved");

      // 验证物理数据库已更新为 approved
      if (drizzle) {
        const rows = await drizzle
          .select()
          .from(pendingApprovals)
          .where(eq(pendingApprovals.id, approvalId));
        expect(rows.length).toBe(1);
        expect(rows[0].status).toBe("approved");
      }
    });
  });

  describe("2. POST /api/v1/spi/escalation/:threadId/reply & close", () => {
    it("should bridge merchant operator reply directly into customer thread", async () => {
      const threadId = `spi_chat_${Date.now()}`;
      const businessId = "adidas";

      await db.createThread(threadId, "u_adi_user", businessId);

      // 商户客服通过 API 回复消息
      const replyRes = await request(app.getHttpServer())
        .post(`/api/v1/spi/escalation/${threadId}/reply`)
        .set("x-tenant-id", "adidas")
        .set("x-api-key", "key_adidas")
        .send({
          message: "您好，我是 Adidas 售后专员，已为您核实到该款跑鞋有现货。",
          operatorId: "adi_rep_102",
          operatorName: "Adidas客服小李",
        });

      expect(replyRes.status).toBe(200);
      expect(replyRes.body.success).toBe(true);

      // 验证消息已存入物理数据库
      const messages = await db.getMessages(threadId);
      const repMsg = messages.find((m) =>
        m.content.includes("我是 Adidas 售后专员"),
      );
      expect(repMsg).toBeDefined();
      expect(repMsg?.role).toBe("assistant");

      // 商户客服结单
      const closeRes = await request(app.getHttpServer())
        .post(`/api/v1/spi/escalation/${threadId}/close`)
        .set("x-tenant-id", "adidas")
        .set("x-api-key", "key_adidas");

      expect(closeRes.status).toBe(200);
      expect(closeRes.body.success).toBe(true);
    });
  });
});
