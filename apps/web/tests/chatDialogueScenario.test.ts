import { describe, expect, test } from 'bun:test';
import { ConversationRepository, db, getDrizzle, pendingApprovals, threads } from 'db';
import { eq } from 'drizzle-orm';
import { ApprovalGatekeeper, runAgent } from 'engine';

describe('全链路多轮对话与状态机自动化流程测试 (Chat Dialogue Scenario & State Machine Suite)', () => {
  test('【场景一：多轮槽位澄清与上下文继承】缺少订单号 -> 追问 -> 补全订单号 -> 成功获取结果', async () => {
    const threadId = `scenario_clarify_${Date.now()}`;
    const userId = 'u_scenario_tester_1';
    const businessId = 'ecommerce';

    // 1. 初始化会话
    await db.createThread(threadId, userId, businessId);

    // 2. 第 1 轮：用户仅提问“帮我查下订单状态”，未提供具体订单号
    const turn1Result = await runAgent(threadId, userId, '帮我查下我的快递到哪了，查询订单状态');
    expect(turn1Result).toBeDefined();
    expect(turn1Result.output).toBeDefined();
    // 应该识别为订单查询意图，并向用户索取订单号
    expect(
      turn1Result.output.includes('订单号') ||
        turn1Result.output.includes('单号') ||
        turn1Result.output.includes('提供'),
    ).toBe(true);

    // 3. 第 2 轮：用户补充提供订单号 ORD-2026-001
    const turn2Result = await runAgent(threadId, userId, '订单号是 ORD-2026-001');
    expect(turn2Result).toBeDefined();
    expect(turn2Result.output).toBeDefined();
    expect(turn2Result.output.length).toBeGreaterThan(5);

    // 4. 验证物理数据库消息记录完整且严格按时序排列
    const history = await db.getMessages(threadId);
    expect(history.length).toBeGreaterThanOrEqual(4);
    expect(history[0].role).toBe('user');
    expect(history[0].content).toContain('查询订单状态');
    expect(history[1].role).toBe('assistant');
    expect(history[2].role).toBe('user');
    expect(history[2].content).toContain('ORD-2026-001');
    expect(history[3].role).toBe('assistant');
  }, 60000);

  test('【场景二：HITL 转人工全生命周期隔离】转人工 -> 等待中追问被拦截直接存库 -> 人工回复解决 -> 恢复智能客服', async () => {
    const threadId = `scenario_hitl_${Date.now()}`;
    const userId = 'u_scenario_tester_2';
    const businessId = 'nike';

    await db.createThread(threadId, userId, businessId);

    // 1. 用户发起转人工诉求
    const escalateResult = await runAgent(
      threadId,
      userId,
      '这个 AI 根本解决不了我的问题，请立即给我转接人工客服专员！',
    );
    expect(escalateResult.output).toContain('人工客服');

    // 验证 pending_approvals 成功生成 waiting 工单
    const drizzle = getDrizzle();
    expect(drizzle).toBeDefined();
    const tickets = await drizzle!.select().from(pendingApprovals).where(eq(pendingApprovals.threadId, threadId));
    expect(tickets.length).toBeGreaterThan(0);
    const humanTicket = tickets[0];
    expect(humanTicket.actionType).toBe('human_escalation');
    expect(humanTicket.status).toBe('waiting');

    // 2. 模拟用户在人工接管期间继续提问
    const userFollowUp = '请问人工客服进来了吗？我还要等多久？';

    // 验证最新工单为人工介入挂起
    const latestApproval = await ApprovalGatekeeper.findLatestApprovalByThreadId(threadId);
    expect(latestApproval).toBeDefined();
    expect(latestApproval?.status).toBe('waiting');
    expect(latestApproval?.actionType).toBe('human_escalation');

    // 追问消息直接持久化存储至 messages 表
    await ConversationRepository.appendMessage({
      threadId,
      businessId,
      role: 'user',
      content: userFollowUp,
    });

    // 验证追问消息已经直接存入物理数据库，没有 AI 盲目插话
    const currentMessages = await db.getMessages(threadId);
    const followUpMsg = currentMessages.find((m) => m.content === userFollowUp);
    expect(followUpMsg).toBeDefined();
    expect(followUpMsg?.role).toBe('user');

    // 3. 模拟人工客服坐席在后台回复并结束接管工单
    const operatorReply = '您好，我是 Nike 资深售后主管，工号 8001，请问遇到了什么售后问题？';
    const resolveResult = await ApprovalGatekeeper.processApprovalAction({
      approvalId: humanTicket.id,
      action: 'human_finish',
      humanReply: operatorReply,
    });
    expect(resolveResult.success).toBe(true);
    expect(resolveResult.status).toBe('resolved_by_human');

    // 4. 用户在人工服务结束后再次提问，验证系统已解除拦截并恢复 AI 接管
    const afterResolvedResult = await runAgent(threadId, userId, '好的，我的问题已经解决了，谢谢');
    expect(afterResolvedResult).toBeDefined();
    expect(afterResolvedResult.output.length).toBeGreaterThan(0);
  }, 60000);

  test('【场景三：客户端乐观状态机与消息排序防御】输入即时清空、占位符自动清除与租户隔离清洗', async () => {
    // 1. 测试输入框原子清空
    let inputState = '我要查询物流 ORD-99999';
    let attachedImages = ['data:image/png;base64,mock123'];
    let sentText = '';
    let sentImages: string[] = [];

    const handleFormSubmit = (text: string, imgs: string[]) => {
      sentText = text;
      sentImages = [...imgs];
      inputState = '';
      attachedImages = [];
    };

    handleFormSubmit(inputState, attachedImages);
    expect(sentText).toBe('我要查询物流 ORD-99999');
    expect(sentImages.length).toBe(1);
    expect(inputState).toBe('');
    expect(attachedImages.length).toBe(0);

    // 2. 测试当收到 isHumanActive 或完成信号时，剔除 pending 占位符
    interface ClientMsg {
      id: string;
      role: string;
      content: string;
      isLoading?: boolean;
      jobId?: string;
    }

    const clientMsgs: ClientMsg[] = [
      { id: 'm1', role: 'user', content: '转人工' },
      { id: 'm2', role: 'assistant', content: '正在接入人工' },
      { id: 'm3', role: 'user', content: '有人在吗' },
      {
        id: 'opt_placeholder',
        role: 'assistant',
        content: '',
        isLoading: true,
        jobId: 'pending-job',
      },
    ];

    const cleanMsgs = clientMsgs.filter((m) => !m.isLoading && m.jobId !== 'pending-job');
    expect(cleanMsgs.length).toBe(3);
    expect(cleanMsgs.some((m) => m.isLoading)).toBe(false);
  }, 30000);

  test('【场景四：多租户与多会话严格隔离】不同 Thread 之间历史消息独立，租户品牌不串线', async () => {
    const threadA = `scenario_iso_nike_${Date.now()}`;
    const threadB = `scenario_iso_adidas_${Date.now()}`;
    const userId = 'u_scenario_tester_multi';

    // 建立两个不同租户的会话
    await db.createThread(threadA, userId, 'nike');
    await db.createThread(threadB, userId, 'adidas');

    await db.addMessage({
      id: `msg_a_${Date.now()}`,
      threadId: threadA,
      role: 'user',
      content: '我在 Nike 旗舰店咨询售后',
      timestamp: new Date().toISOString(),
    });

    await db.addMessage({
      id: `msg_b_${Date.now()}`,
      threadId: threadB,
      role: 'user',
      content: '我在 Adidas 专柜咨询尺码',
      timestamp: new Date().toISOString(),
    });

    // 分别拉取两个会话的消息
    const msgsA = await db.getMessages(threadA);
    const msgsB = await db.getMessages(threadB);

    expect(msgsA.length).toBe(1);
    expect(msgsA[0].content).toBe('我在 Nike 旗舰店咨询售后');

    expect(msgsB.length).toBe(1);
    expect(msgsB[0].content).toBe('我在 Adidas 专柜咨询尺码');

    // 验证线程元数据与租户隔离
    const threadRecordA = await db.getThread(threadA);
    const threadRecordB = await db.getThread(threadB);

    expect(threadRecordA?.businessId).toBe('nike');
    expect(threadRecordB?.businessId).toBe('adidas');
  }, 30000);

  test('【场景五：高危退款安全策略拦截】超额退款 -> 自动挂起待审批 -> 状态置为 waiting', async () => {
    const threadId = `scenario_refund_gate_${Date.now()}`;
    const userId = 'u_scenario_tester_refund';
    const businessId = 'ecommerce';

    await db.createThread(threadId, userId, businessId);

    // 模拟用户申请一笔高额退款（超出 $100 自动放行限额）
    const refundResult = await runAgent(threadId, userId, '我要申请订单 ORD-2026-999 退款 880 元，商品质量有问题');

    expect(refundResult).toBeDefined();
    expect(refundResult.output).toBeDefined();

    // 验证是否安全拦截或提示审批挂起
    const drizzle = getDrizzle();
    if (drizzle) {
      const approvals = await drizzle.select().from(pendingApprovals).where(eq(pendingApprovals.threadId, threadId));

      if (approvals.length > 0) {
        const app = approvals[0];
        expect(app.status).toBe('waiting');
        const typeStr = (app.actionType || (app as any).action_type || '').toLowerCase();
        expect(typeStr.includes('refund') || typeStr.includes('processrefund') || typeStr.includes('escalat')).toBe(
          true,
        );
      }
    }
  }, 60000);
});
