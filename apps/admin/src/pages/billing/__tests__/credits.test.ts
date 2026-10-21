import { afterEach, describe, expect, it, mock } from 'bun:test';
import { billingApi } from '../../../lib/api';
import { describeCreditReason, formatCreditDelta, validateCreditAdjust } from '../credits';

// admin 册是 bun test(无 jsdom/DOM):组件渲染不在此钉(merchant-admin vitest
// 册有 jsdom 组件钉),本册钉 transport 契约(调整提交体)与呈现层纯函数。

type CapturedCall = { input: string | URL; init?: RequestInit };

function installFetchMock(responder: (call: CapturedCall) => { status: number; body: unknown }) {
  const calls: CapturedCall[] = [];
  const fetchMock = mock((input: string | URL, init?: RequestInit) => {
    const call = { input, init };
    calls.push(call);
    const { status, body } = responder(call);
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  });
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return calls;
}

// bun test 全部用例共进程共享 globals:fetch 桩用毕必须还原,
// 否则连带把其它 bun 册(如 adminModulesApiIntegration 直连真 fetch)打红
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe('billingApi 积分池 transport 契约', () => {
  it('adjustCredits:POST /api/billing/credits/adjust,提交体为 {businessId, delta, reason}', async () => {
    const calls = installFetchMock(() => ({
      status: 200,
      body: { success: true, data: { businessId: 'aurora', balance: 1300 } },
    }));
    const res = await billingApi.adjustCredits('aurora', 500, '双十一活动赠送');
    expect(res.success).toBe(true);
    expect(res.data?.balance).toBe(1300);
    expect(calls).toHaveLength(1);
    const url = String(calls[0].input);
    expect(url.endsWith('/api/billing/credits/adjust')).toBe(true);
    expect(calls[0].init?.method).toBe('POST');
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      businessId: 'aurora',
      delta: 500,
      reason: '双十一活动赠送',
    });
  });

  it('adjustCredits:负 delta(核减)原样进提交体', async () => {
    const calls = installFetchMock(() => ({
      status: 200,
      body: { success: true, data: { businessId: 'aurora', balance: 800 } },
    }));
    await billingApi.adjustCredits('aurora', -200, '多扣回冲');
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      businessId: 'aurora',
      delta: -200,
      reason: '多扣回冲',
    });
  });

  it('adjustCredits:服务端 400 业务拒绝(reason 空/穿零)原样返 body,不 throw', async () => {
    installFetchMock(() => ({
      status: 400,
      body: { success: false, error: '核减后余额不能为负(或商户账户不可用)' },
    }));
    const res = await billingApi.adjustCredits('aurora', -99999, '压测核减');
    expect(res.success).toBe(false);
    expect(res.error).toBe('核减后余额不能为负(或商户账户不可用)');
  });

  it('getCredits:GET /api/billing/credits/{businessId}(编码透传),balance null 诚实保留', async () => {
    const calls = installFetchMock(() => ({
      status: 200,
      body: {
        success: true,
        data: {
          businessId: 'aurora',
          balance: null,
          transactions: [
            { id: 't1', delta: 1000, reason: 'initial_grant', refJobId: null, operator: null, createdAt: null },
          ],
        },
      },
    }));
    const res = await billingApi.getCredits('aurora');
    expect(res.success).toBe(true);
    expect(res.data?.balance).toBe(null); // 未初始化严禁被前端编成 0
    expect(res.data?.transactions).toHaveLength(1);
    expect(String(calls[0].input).endsWith('/api/billing/credits/aurora')).toBe(true);
    expect(calls[0].init?.method).toBe('GET');
  });
});

describe('积分调整客户端校验(validateCreditAdjust)', () => {
  it('reason 必填(审计口径):空白即拒', () => {
    expect(validateCreditAdjust('500', '')).toBe('调整原因必填(审计口径)');
    expect(validateCreditAdjust('500', '   ')).toBe('调整原因必填(审计口径)');
  });

  it('delta 0 / 非法 / 非整数各拒,文案指明正负号语义', () => {
    expect(validateCreditAdjust('0', '充值')).toBe('调整数值不能为 0(充值请输入正数,核减请输入负数)');
    expect(validateCreditAdjust('abc', '充值')).toBe('请输入有效的调整数值');
    expect(validateCreditAdjust('', '充值')).toBe('请输入有效的调整数值');
    expect(validateCreditAdjust('1.5', '充值')).toBe('调整数值必须是整数(1 次问询 = 1 积分)');
  });

  it('合法提交(正充值/负核减)返回 null 放行', () => {
    expect(validateCreditAdjust('500', '双十一活动赠送')).toBe(null);
    expect(validateCreditAdjust('-200', '多扣回冲')).toBe(null);
  });
});

describe('积分流水呈现(describeCreditReason / formatCreditDelta)', () => {
  it('台账机读枚举转人话;admin_adjust 复合形态拆前缀', () => {
    expect(describeCreditReason('initial_grant')).toBe('初始赠送');
    expect(describeCreditReason('consume')).toBe('问询消耗');
    expect(describeCreditReason('refund')).toBe('失败退回');
    expect(describeCreditReason('admin_adjust')).toBe('平台调整');
    expect(describeCreditReason('admin_adjust: 双十一活动赠送')).toBe('平台调整:双十一活动赠送');
  });

  it('未知 reason / 缺值诚实透传,不编造', () => {
    expect(describeCreditReason('some_future_reason')).toBe('some_future_reason');
    expect(describeCreditReason(null)).toBe('—');
    expect(describeCreditReason('')).toBe('—');
  });

  it('delta 呈现:正数带 +,负数原生带 -,缺值「—」', () => {
    expect(formatCreditDelta(500)).toBe('+500');
    expect(formatCreditDelta(-1)).toBe('-1');
    expect(formatCreditDelta(0)).toBe('0');
    expect(formatCreditDelta(null)).toBe('—');
  });
});
