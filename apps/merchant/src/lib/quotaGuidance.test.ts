// @vitest-environment node
// 配额拒回复映射契约(2026-10-21 配额闸票 06):store chat 信封 quotaCode +
// output(后端权威文案)→ 引导气泡文案。游客(guest-*)带注册/登录引导,
// 其余照实显示 output;诚实律:不编造剩余额度数字。
import { describe, expect, it } from 'vitest';
import { QUOTA_CODES, isGuestUserId, quotaReplyText } from './quotaGuidance';

const OUT_GUEST = '您的免费问询次数已用完，注册或登录后可继续使用智能服务。';
const OUT_IP = '当前网络环境的免费试用额度已用完，请注册或登录后继续使用。';
const OUT_DAILY = '您今日的问询次数已达上限，请明天再试。';
const OUT_EXHAUSTED = '当前商户的服务额度已用尽，请联系商户充值后继续使用。';

describe('quotaReplyText 配额拒回复映射(配额闸票 06,merchant 面)', () => {
  it('游客 + QUOTA_GUEST_LIMIT:后端文案照实在前 + 注册/登录引导', () => {
    const text = quotaReplyText('QUOTA_GUEST_LIMIT', OUT_GUEST, 'guest-ab12cd34');
    expect(text.startsWith(OUT_GUEST)).toBe(true);
    expect(text).toContain('注册');
    expect(text).toContain('登录');
  });

  it('游客 + QUOTA_IP_LIMIT:同样引导注册/登录', () => {
    const text = quotaReplyText('QUOTA_IP_LIMIT', OUT_IP, 'guest-ab12cd34');
    expect(text.startsWith(OUT_IP)).toBe(true);
    expect(text).toContain('注册');
    expect(text).toContain('登录');
  });

  it('登录顾客(CUST-WEB-*)+ QUOTA_USER_DAILY:照实显示 output,不附加引导', () => {
    expect(quotaReplyText('QUOTA_USER_DAILY', OUT_DAILY, 'CUST-WEB-mz8x1')).toBe(OUT_DAILY);
  });

  it('登录顾客 + QUOTA_MERCHANT_EXHAUSTED:照实显示 output', () => {
    expect(quotaReplyText('QUOTA_MERCHANT_EXHAUSTED', OUT_EXHAUSTED, 'CUST-8801')).toBe(OUT_EXHAUSTED);
  });

  it('游客撞商户池尽:注册帮不上忙,照实显示 output 不误导', () => {
    expect(quotaReplyText('QUOTA_MERCHANT_EXHAUSTED', OUT_EXHAUSTED, 'guest-ab12cd34')).toBe(OUT_EXHAUSTED);
  });

  it('诚实律:后端文案无数字时,拼装结果不引入任何额度数字', () => {
    expect(/\d/.test(quotaReplyText('QUOTA_GUEST_LIMIT', OUT_GUEST, 'guest-ab12cd34'))).toBe(false);
    expect(/\d/.test(quotaReplyText('QUOTA_USER_DAILY', OUT_DAILY, 'CUST-WEB-mz8x1'))).toBe(false);
  });

  it('未知码不猜:只透传后端 output', () => {
    expect(quotaReplyText('QUOTA_FUTURE_CODE', '后端给的文案', 'guest-ab12cd34')).toBe('后端给的文案');
  });

  it('output 缺失(防御臂):诚实说明被拒,不空白、不编造详情', () => {
    const guest = quotaReplyText('QUOTA_GUEST_LIMIT', '', 'guest-ab12cd34');
    expect(guest).toContain('未能受理');
    expect(guest).toContain('注册');
    expect(/\d/.test(guest)).toBe(false);
    expect(quotaReplyText('QUOTA_USER_DAILY', '', 'CUST-1')).toBe('本次问询未能受理。');
  });

  it('isGuestUserId:guest- 前缀判定(CUST-* 真客隔断)', () => {
    expect(isGuestUserId('guest-abc123')).toBe(true);
    expect(isGuestUserId('CUST-WEB-1')).toBe(false);
    expect(isGuestUserId('CUST-8801')).toBe(false);
    expect(isGuestUserId('')).toBe(false);
  });

  it('机读码闭集(quota.py 四码)', () => {
    expect(QUOTA_CODES).toEqual([
      'QUOTA_GUEST_LIMIT',
      'QUOTA_IP_LIMIT',
      'QUOTA_USER_DAILY',
      'QUOTA_MERCHANT_EXHAUSTED',
    ]);
  });
});
