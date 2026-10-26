import { CARD_ACTIONS } from 'types';
// 坐席推卡构造层契约(客服优化批 2026-10-25):卡片形状落在 packages/types
// 判别联合内、动作名落在 CARD_ACTIONS 闭集内(merchant 侧 12 名全登记)、
// 轨迹卡零伪造节点(数据诚实律)。
import { describe, expect, it } from 'vitest';
import {
  CARRIER_OPTIONS,
  QUICK_REPLY_PRESETS,
  buildOrderCard,
  buildQuickRepliesCard,
  buildShippedTrackingCard,
  carrierLabelOf,
} from './live-desk-cards';

const ACTION_SET = new Set<string>(CARD_ACTIONS);

describe('buildOrderCard 订单卡', () => {
  it('形状对齐 OrderCardData,动作闭集内且带单号 payload', () => {
    const card = buildOrderCard({
      orderId: 'ORD-1',
      status: 'PAID',
      totalAmount: 299,
      createdAt: '2026-10-25T10:00:00',
    });
    expect(card.type).toBe('order_card');
    if (card.type !== 'order_card') return;
    expect(card.data.orderId).toBe('ORD-1');
    // 顾客可见面走正典中文词面(orderStatusMeta 单点),原始英文码不外显
    expect(card.data.status).toBe('待发货');
    expect(card.data.totalAmount).toBe(299);
    expect(card.data.actions?.length).toBe(2);
    for (const a of card.data.actions || []) {
      expect(ACTION_SET.has(a.action)).toBe(true);
    }
    const track = card.data.actions?.find((a) => a.action === 'track_order');
    expect(track?.payload?.orderId).toBe('ORD-1');
  });

  it('createdAt 缺值不编造(undefined 不落键)', () => {
    const card = buildOrderCard({ orderId: 'ORD-2', status: 'SHIPPED', totalAmount: 1, createdAt: null });
    if (card.type !== 'order_card') return;
    expect(card.data.createdAt).toBeUndefined();
  });
});

describe('buildShippedTrackingCard 发货通知卡(诚实单节点)', () => {
  it('单节点「已发货 + 轨迹待更新」,零伪造在途/派送节点', () => {
    const card = buildShippedTrackingCard('京东快递', 'JD888');
    expect(card.type).toBe('tracking_timeline');
    if (card.type !== 'tracking_timeline') return;
    expect(card.data.carrier).toBe('京东快递');
    expect(card.data.trackingNumber).toBe('JD888');
    expect(card.data.currentStatus).toBe('已发货');
    expect(card.data.timeline).toHaveLength(1);
    const node = card.data.timeline[0];
    expect(node.description).toContain('轨迹待更新');
    expect(node.description).toContain('JD888');
    const json = JSON.stringify(card);
    expect(json).not.toContain('揽收');
    expect(json).not.toContain('派送中');
    expect(json).not.toContain('运输中');
  });
});

describe('buildQuickRepliesCard 快捷选项卡', () => {
  it('选项动作恒 send_message 且 payload.text = 选项文案(点选回流成消息)', () => {
    const preset = QUICK_REPLY_PRESETS[0];
    const card = buildQuickRepliesCard(preset);
    expect(card.type).toBe('quick_replies');
    if (card.type !== 'quick_replies') return;
    expect(card.data.title).toBe(preset.title);
    expect(card.data.options).toHaveLength(preset.options.length);
    for (const opt of card.data.options) {
      expect(opt.action).toBe('send_message');
      expect(ACTION_SET.has(opt.action)).toBe(true);
      expect(opt.payload?.text).toBe(opt.label);
    }
  });

  it('预设至少一组且选项非空', () => {
    expect(QUICK_REPLY_PRESETS.length).toBeGreaterThanOrEqual(1);
    for (const p of QUICK_REPLY_PRESETS) {
      expect(p.options.length).toBeGreaterThan(0);
    }
  });
});

describe('承运商词表', () => {
  it('四承运商齐备;未知编码原样透传不编造', () => {
    expect(CARRIER_OPTIONS.map((c) => c.code)).toEqual(['SF', 'JD', 'ZTO', 'EMS']);
    expect(carrierLabelOf('SF')).toBe('顺丰速运');
    expect(carrierLabelOf('UNKNOWN-X')).toBe('UNKNOWN-X');
  });
});
