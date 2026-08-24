import { describe, expect, it } from 'bun:test';
import { NextRequest } from 'next/server';
import { GET as getApprovalsRoute, POST as postApprovalsRoute } from '../app/api/admin/approvals/route';
import { GET as getConversationTimelineRoute } from '../app/api/admin/conversations/[threadId]/route';
import { GET as getConversationsRoute } from '../app/api/admin/conversations/route';

describe('🛡️ Merchant Approvals & LiveDesk Integration Suite', () => {
  it('1. 应该能成功获取商户待办审核列表', async () => {
    const req = new NextRequest('http://localhost:3005/api/admin/approvals?tenantId=aurora');
    const res = await getApprovalsRoute(req);
    expect(res.status).toBe(200);

    const json = await res.json();
    expect(json.success).toBe(true);
    expect(Array.isArray(json.approvals)).toBe(true);
    expect(typeof json.total).toBe('number');
  });

  it('2. 应该能发起人工客服接管会话', async () => {
    const threadId = `merchant_test_thread_${Date.now()}`;
    const req = new NextRequest('http://localhost:3005/api/admin/approvals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        threadId,
        action: 'start_human_takeover',
      }),
    });

    const res = await postApprovalsRoute(req);
    expect(res.status).toBe(200);

    const json = await res.json();
    expect(json.success).toBe(true);
    expect(json.approvalId).toBeDefined();

    // 校验回复人工消息
    const replyReq = new NextRequest('http://localhost:3005/api/admin/approvals', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        approvalId: json.approvalId,
        action: 'human_message',
        humanReply: '您好，我是极光潮品商户客服，很高兴为您服务！',
      }),
    });

    const replyRes = await postApprovalsRoute(replyReq);
    expect(replyRes.status).toBe(200);
    const replyJson = await replyRes.json();
    expect(replyJson.success).toBe(true);
  });

  it('3. 应该能查询商户会话列表及特定会话时间轴', async () => {
    const listReq = new NextRequest('http://localhost:3005/api/admin/conversations?tenantId=aurora');
    const listRes = await getConversationsRoute(listReq);
    expect(listRes.status).toBe(200);

    const listJson = await listRes.json();
    expect(listJson.success).toBe(true);
    expect(Array.isArray(listJson.conversations)).toBe(true);

    const testThreadId = 'default_thread';
    const detailReq = new NextRequest(`http://localhost:3005/api/admin/conversations/${testThreadId}?tenantId=aurora`);
    const detailRes = await getConversationTimelineRoute(detailReq, {
      params: Promise.resolve({ threadId: testThreadId }),
    });

    expect(detailRes.status).toBe(200);
    const detailJson = await detailRes.json();
    expect(detailJson.success).toBe(true);
  });
});
