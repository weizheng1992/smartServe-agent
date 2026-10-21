// 配额拒引导映射契约(2026-10-21 配额闸票 06):机读码 → 建议文案闭集 +
// 气泡拼装(后端 output 照实在前)。web 面 runner 为 bun test(与既有 lib
// 测试同册),映射逻辑与 runner 无关。
import { describe, expect, test } from 'bun:test';
import { QUOTA_CODES, isQuotaCode, quotaAdviceOf, quotaBubbleText } from './quotaGuidance';

describe('quotaGuidance 配额拒引导映射(配额闸票 06)', () => {
  test('QUOTA_USER_DAILY → 「明天再试」建议', () => {
    expect(quotaAdviceOf('QUOTA_USER_DAILY')).toBe('明天再试');
    const text = quotaBubbleText('QUOTA_USER_DAILY', '您今日的问询次数已达上限，请明天再试。');
    expect(text.startsWith('您今日的问询次数已达上限，请明天再试。')).toBe(true);
    expect(text).toContain('建议您：明天再试');
  });

  test('QUOTA_MERCHANT_EXHAUSTED → 「联系商户」建议', () => {
    expect(quotaAdviceOf('QUOTA_MERCHANT_EXHAUSTED')).toBe('联系商户');
    const text = quotaBubbleText('QUOTA_MERCHANT_EXHAUSTED', '当前商户的服务额度已用尽，请联系商户充值后继续使用。');
    expect(text).toContain('当前商户的服务额度已用尽，请联系商户充值后继续使用。');
    expect(text).toContain('建议您：联系商户');
  });

  test('QUOTA_GUEST_LIMIT / QUOTA_IP_LIMIT → 引导注册/登录(web 面理论不可达,兜底臂)', () => {
    for (const code of ['QUOTA_GUEST_LIMIT', 'QUOTA_IP_LIMIT']) {
      expect(quotaAdviceOf(code)).toContain('注册');
      expect(quotaAdviceOf(code)).toContain('登录');
    }
  });

  test('诚实律:后端 output 照实在前,映射不引入任何额度数字', () => {
    const text = quotaBubbleText('QUOTA_USER_DAILY', '您今日的问询次数已达上限，请明天再试。');
    // 输入无数字,拼装结果也不得无中生有剩余次数
    expect(/\d/.test(text)).toBe(false);
  });

  test('未知码不猜:建议为空,气泡只透传后端 output', () => {
    expect(quotaAdviceOf('QUOTA_FUTURE_CODE')).toBe('');
    expect(quotaBubbleText('QUOTA_FUTURE_CODE', '后端给的文案')).toBe('后端给的文案');
    expect(isQuotaCode('QUOTA_FUTURE_CODE')).toBe(false);
  });

  test('output 缺失(防御臂):诚实说明被拒并给建议,不空白、不编造详情', () => {
    const text = quotaBubbleText('QUOTA_MERCHANT_EXHAUSTED', '');
    expect(text).toContain('未能受理');
    expect(text).toContain('联系商户');
    expect(/\d/.test(text)).toBe(false);
  });

  test('机读码闭集(quota.py 四码)', () => {
    expect(QUOTA_CODES).toEqual(['QUOTA_GUEST_LIMIT', 'QUOTA_IP_LIMIT', 'QUOTA_USER_DAILY', 'QUOTA_MERCHANT_EXHAUSTED']);
    for (const code of QUOTA_CODES) {
      expect(isQuotaCode(code)).toBe(true);
    }
    expect(isQuotaCode(undefined)).toBe(false);
    expect(isQuotaCode(42)).toBe(false);
  });
});
