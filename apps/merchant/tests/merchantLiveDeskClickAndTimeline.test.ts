import { describe, expect, it } from 'bun:test';
import { ConversationRepository } from 'db';
import { NextRequest } from 'next/server';
import { POST as postApprovalsRoute } from '../app/api/admin/approvals/route';
import { GET as getConversationTimelineRoute } from '../app/api/admin/conversations/[threadId]/route';
import { GET as getConversationsRoute } from '../app/api/admin/conversations/route';

describe('💬 Merchant LiveDesk Click & Dialogue Interactive Suite', () => {
  const tenantId = 'aurora';
  const testThreadId = `test_thread_interactive_${Date.now()}`;

  it('1. 应该能通过 API 写入会话并从会话列表中检索到包含 id 和 threadId 的项', async () => {
    // 写入模拟消息创建会话
    await ConversationRepository.appendMessage({
      threadId: testThreadId,
      businessId: tenantId,
      userId: 'cust_interactive_01',
      role: 'user',
      content: '你好，请问你们发什么快递？',
    });

    await ConversationRepository.appendMessage({
      threadId: testThreadId,
      businessId: tenantId,
      role: 'assistant',
      content: '您好！我们默认使用顺丰速运进行配送。',
    });

    // 请求商户后台会话列表 API
    const listReq = new NextRequest(`http://localhost:3005/api/admin/conversations?tenantId=${tenantId}`);
    const listRes = await getConversationsRoute(listReq);
    expect(listRes.status).toBe(200);

    const listJson = await listRes.json();
    expect(listJson.success).toBe(true);
    expect(Array.isArray(listJson.conversations)).toBe(true);

    // 查找刚刚创建的会话
    const found = listJson.conversations.find((c: any) => c.threadId === testThreadId || c.id === testThreadId);
    expect(found).toBeDefined();
    // 关键验证：前端点击所依赖的 id 或 threadId 必须存在且非空
    expect(found.id).toBe(testThreadId);
    expect(found.threadId).toBe(testThreadId);
  });

  it('2. 模拟前端点击会话卡片：通过点击取得的 id 拉取时间轴消息并验证时序', async () => {
    const detailReq = new NextRequest(
      `http://localhost:3005/api/admin/conversations/${testThreadId}?tenantId=${tenantId}`,
    );
    const detailRes = await getConversationTimelineRoute(detailReq, {
      params: Promise.resolve({ threadId: testThreadId }),
    });

    expect(detailRes.status).toBe(200);
    const detailJson = await detailRes.json();
    expect(detailJson.success).toBe(true);
    expect(detailJson.data).toBeDefined();
    expect(Array.isArray(detailJson.data.messages)).toBe(true);
    expect(detailJson.data.messages.length).toBeGreaterThanOrEqual(2);

    const firstMsg = detailJson.data.messages[0];
    expect(firstMsg.role).toBe('user');
    expect(firstMsg.content).toBe('你好，请问你们发什么快递？');
  });

  it('3. 客服在已选会话中发送回复：验证人工消息追加与状态机流转', async () => {
    // 1. 发起接管
    const takeoverReq = new NextRequest('http://localhost:3005/api/admin/approvals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        threadId: testThreadId,
        action: 'start_human_takeover',
      }),
    });
    const takeoverRes = await postApprovalsRoute(takeoverReq);
    const takeoverJson = await takeoverRes.json();
    expect(takeoverJson.success).toBe(true);

    // 2. 发送客服消息
    const sendReq = new NextRequest('http://localhost:3005/api/admin/approvals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        approvalId: takeoverJson.approvalId,
        threadId: testThreadId,
        action: 'human_message',
        humanReply: '客服为您核实中，支持顺丰次日达哦！',
      }),
    });
    const sendRes = await postApprovalsRoute(sendReq);
    expect(sendRes.status).toBe(200);

    // 3. 再次查询时间轴确认消息已物理持久化
    const checkReq = new NextRequest(
      `http://localhost:3005/api/admin/conversations/${testThreadId}?tenantId=${tenantId}`,
    );
    const checkRes = await getConversationTimelineRoute(checkReq, {
      params: Promise.resolve({ threadId: testThreadId }),
    });
    const checkJson = await checkRes.json();
    const msgs = checkJson.data.messages;
    const lastMsg = msgs[msgs.length - 1];
    expect(lastMsg.role).toBe('assistant');
    expect(lastMsg.content).toContain('顺丰次日达');
  });
});
