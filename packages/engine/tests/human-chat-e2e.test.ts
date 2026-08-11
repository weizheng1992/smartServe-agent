import { describe, expect, test } from "bun:test";
import { db, getDrizzle, pendingApprovals } from "db";
import { eq } from "drizzle-orm";
import { runAgent } from "../src/graph/buildGraph";

describe("Human Support Operator Takeover & IM Chat Full E2E Lifecycle Test", () => {
  test("Full lifecycle: User Escalation -> Pending Approval Ticket -> Human Reply -> Resume Agent", async () => {
    const threadId = `e2e_human_chat_thread_${Date.now()}`;
    const userId = "u_human_e2e_customer";
    const userEscalationMessage =
      "请问有人吗？我要转接人工客服处理我的换货请求！";

    console.log(
      "[E2E Test Step 1] Step 1: User requests human support escalation...",
    );

    // 1. Run agent with user escalation message
    const initialResult = await runAgent(
      threadId,
      userId,
      userEscalationMessage,
    );

    expect(initialResult).toBeDefined();
    expect(initialResult.output).toBeDefined();
    expect(initialResult.output).toContain("人工客服");

    console.log(
      "[E2E Test Step 1 Success] Output:",
      initialResult.output.substring(0, 100),
    );

    // 2. Verify physical database state for pending_approvals record
    console.log(
      "[E2E Test Step 2] Step 2: Verifying database pending_approvals record...",
    );
    const drizzle = getDrizzle();
    expect(drizzle).toBeDefined();

    const tickets = await drizzle!
      .select()
      .from(pendingApprovals)
      .where(eq(pendingApprovals.threadId, threadId));

    expect(tickets.length).toBeGreaterThan(0);
    const pendingTicket = tickets[0];
    expect(pendingTicket.actionType).toBe("human_escalation");
    expect(pendingTicket.status).toBe("waiting");

    console.log(
      "[E2E Test Step 2 Success] Found pending ticket ID:",
      pendingTicket.id,
    );

    // 3. Verify conversation history fetching for Admin IM Chat Modal
    console.log(
      "[E2E Test Step 3] Step 3: Fetching thread conversation history for Admin IM Modal...",
    );
    const threadMessages = await db.getMessages(threadId);
    expect(threadMessages).toBeDefined();
    expect(threadMessages.length).toBeGreaterThan(0);

    const userMsg = threadMessages.find((m: any) => m.role === "user");
    expect(userMsg).toBeDefined();
    expect(userMsg.content).toBe(userEscalationMessage);

    console.log(
      "[E2E Test Step 3 Success] Thread history contains",
      threadMessages.length,
      "messages.",
    );

    // 4. Simulate Human Operator sending reply via Admin Approval API handler
    console.log(
      "[E2E Test Step 4] Step 4: Simulating Human Support Operator reply & ticket resolution...",
    );
    const operatorReplyText =
      "您好！我是人工高级客服主管。我已核实您的情况，将为您进行退换货绿色通道安排。";

    // Simulate approval endpoint updates:
    const updatedPayload = {
      ...(pendingTicket.actionPayload as Record<string, any>),
      humanReply: operatorReplyText,
      resolvedAt: new Date().toISOString(),
    };

    await drizzle!
      .update(pendingApprovals)
      .set({
        status: "resolved_by_human",
        actionPayload: updatedPayload,
      })
      .where(eq(pendingApprovals.id, pendingTicket.id));

    // Save human operator reply message into thread database
    await db.addMessage({
      id: `msg_human_reply_${Date.now()}`,
      threadId,
      role: "assistant",
      content: `【人工客服回复】: ${operatorReplyText}`,
      timestamp: new Date().toISOString(),
    });

    // 5. Verify database status updated to resolved_by_human
    const updatedTickets = await drizzle!
      .select()
      .from(pendingApprovals)
      .where(eq(pendingApprovals.id, pendingTicket.id));

    expect(updatedTickets[0].status).toBe("resolved_by_human");
    expect((updatedTickets[0].actionPayload as any).humanReply).toBe(
      operatorReplyText,
    );

    console.log(
      "[E2E Test Step 4 Success] Approval ticket status updated to resolved_by_human.",
    );

    // 6. Resume Agent execution with System prompt injection
    console.log(
      "[E2E Test Step 5] Step 5: Resuming agent workflow with human reply context...",
    );
    const systemResumePrompt = `System: Human support operator responded to the user: "${operatorReplyText}". Please present this response politely to the user in Chinese and resume normal support.`;

    const resumeResult = await runAgent(threadId, userId, systemResumePrompt);

    expect(resumeResult).toBeDefined();
    expect(resumeResult.output).toBeDefined();
    expect(typeof resumeResult.output).toBe("string");
    expect(resumeResult.output.length).toBeGreaterThan(10);

    console.log(
      "[E2E Test Step 5 Success] Resumed Output:",
      resumeResult.output.substring(0, 100),
    );

    // 7. Verify thread messages now contain full back-and-forth chat
    const finalMessages = await db.getMessages(threadId);
    expect(finalMessages.length).toBeGreaterThanOrEqual(3);

    console.log(
      "[E2E Test Complete] All 7 steps in the Human Support E2E lifecycle test passed!",
    );
  }, 120000);
});
