import { describe, expect, test } from 'bun:test';
import { CARD_ACTIONS } from 'types';
import { CARD_ACTION_HANDLERS, resolveCardActionMessage } from './cardActions';

describe('cardActions 卡片动作目录闭集(F3 契约,2026-10-07 夜评补钉)', () => {
  test('CARD_ACTIONS 目录闭集:引擎新动作须显式改此册(编译期穷举之外的运行时钉)', () => {
    const expected: string[] = [
      'send_message',
      'select_order',
      'track_order',
      'request_refund',
      'confirm_refund',
      'submit_return_tracking',
      'submit_step_action',
      'add_to_cart_interactive',
      'buy_now_interactive',
      'checkout_cart',
      'view_cart',
      'clear_cart',
    ];
    expect([...CARD_ACTIONS].sort() as string[]).toEqual(expected.sort());
  });

  test('分发表键集与目录闭集严格相等(缺键=引擎新动作未接,多键=死词)', () => {
    expect(Object.keys(CARD_ACTION_HANDLERS).sort()).toEqual([...CARD_ACTIONS].sort());
  });
});

describe('cardActions 卡片动作分发表(2026-10-02 夜审修复A)', () => {
  test('引擎购物车卡实发的三动作必须产消息(此前两处消费方均为死按钮)', () => {
    expect(resolveCardActionMessage('checkout_cart', {})).toBe('去结算');
    expect(resolveCardActionMessage('view_cart', {})).toBe('查看购物车');
    expect(resolveCardActionMessage('clear_cart', {})).toBe('清空购物车');
  });

  test('购物车文案必须是引擎真实触发词(裸「结算」是查看摘要旧契约,严禁用)', () => {
    // checkout_cart 的词面须命中 intent_registry.CHECKOUT_TRIGGER_PATTERN
    // (_pick(CHECKOUT_FAMILY, 0..3)),严禁落入裸「结算」查看分支
    expect(CARD_ACTION_HANDLERS.checkout_cart({})).not.toBe('结算');
    expect(CARD_ACTION_HANDLERS.checkout_cart({})).toBe('去结算');
  });

  test('订单族动作缺 orderId 守卫:必须返回 null,不得发送残句', () => {
    expect(resolveCardActionMessage('select_order', {})).toBeNull();
    expect(resolveCardActionMessage('track_order', {})).toBeNull();
    expect(resolveCardActionMessage('request_refund', {})).toBeNull();
    expect(resolveCardActionMessage('confirm_refund', {})).toBeNull();
    expect(resolveCardActionMessage('track_order', { orderId: 'ORD-1' })).toBe('帮我查一下订单 ORD-1 的物流轨迹');
  });

  test('send_message 直通 payload.text;缺 text 返回 null', () => {
    expect(resolveCardActionMessage('send_message', { text: '退货政策是什么' })).toBe('退货政策是什么');
    expect(resolveCardActionMessage('send_message', {})).toBeNull();
  });

  test('未登记动作回落 payload.query;无 query 诚实 null(不再静默 no-op)', () => {
    expect(resolveCardActionMessage('unknown_action', { query: '查物流' })).toBe('查物流');
    expect(resolveCardActionMessage('unknown_action', {})).toBeNull();
  });

  test('交互式加购/立即购买组装规格与数量', () => {
    expect(
      resolveCardActionMessage('add_to_cart_interactive', {
        title: '极光慢跑裤',
        skuTitle: '炭黑 M码',
        quantity: 2,
      }),
    ).toBe('我想将 极光慢跑裤（规格: 炭黑 M码）购买 2 件加入购物车');
    expect(resolveCardActionMessage('buy_now_interactive', { title: '极光慢跑裤', skuId: 'SKU-1', quantity: 1 })).toBe(
      '我想立即购买 极光慢跑裤（规格: SKU-1）共 1 件',
    );
  });
});
