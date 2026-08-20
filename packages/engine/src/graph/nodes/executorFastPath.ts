import { extractOrderId } from './utils';

export interface ParsedToolCall {
  toolName: string;
  args: Record<string, unknown>;
}

export function tryMatchExecutorFastPath(
  description: string,
  userInput: string,
  allowedTools: string[],
  shortMemory?: any[],
): ParsedToolCall | null {
  const descLower = description.toLowerCase();
  const inputLower = (userInput || '').toLowerCase();
  const extractedOrderId = extractOrderId(description, userInput, shortMemory);

  if (
    (descLower.includes('refund') || descLower.includes('processrefund') || descLower.includes('退款')) &&
    allowedTools.includes('processRefund') &&
    extractedOrderId
  ) {
    return {
      toolName: 'processRefund',
      args: {
        orderId: extractedOrderId,
        reason: 'Customer requested refund via smartServe',
      },
    };
  }

  if (
    (descLower.includes('status') ||
      descLower.includes('carrier') ||
      descLower.includes('track') ||
      descLower.includes('getorderstatus') ||
      descLower.includes('物流') ||
      descLower.includes('进度') ||
      descLower.includes('发货')) &&
    allowedTools.includes('getOrderStatus') &&
    extractedOrderId
  ) {
    return {
      toolName: 'getOrderStatus',
      args: { orderId: extractedOrderId },
    };
  }

  if (
    (descLower.includes('listuserorders') ||
      descLower.includes('list orders') ||
      descLower.includes('全部订单') ||
      descLower.includes('历史订单') ||
      descLower.includes('名下订单')) &&
    allowedTools.includes('listUserOrders')
  ) {
    return {
      toolName: 'listUserOrders',
      args: {},
    };
  }

  if (
    (descLower.includes('screenshot') ||
      descLower.includes('takescreenshot') ||
      descLower.includes('截图') ||
      descLower.includes('快照')) &&
    allowedTools.includes('takeScreenshot')
  ) {
    return {
      toolName: 'takeScreenshot',
      args: {
        url: 'http://localhost:3000',
      },
    };
  }

  if (
    (descLower.includes('preference') ||
      descLower.includes('recorduserpreference') ||
      descLower.includes('偏好') ||
      descLower.includes('尺码') ||
      descLower.includes('鞋码')) &&
    allowedTools.includes('recordUserPreference')
  ) {
    let prefType = 'other';
    if (inputLower.includes('码') || inputLower.includes('尺码') || inputLower.includes('size')) {
      prefType = 'size';
    } else if (inputLower.includes('色') || inputLower.includes('颜色') || inputLower.includes('color')) {
      prefType = 'color';
    } else if (inputLower.includes('牌') || inputLower.includes('品牌') || inputLower.includes('brand')) {
      prefType = 'brand';
    }

    return {
      toolName: 'recordUserPreference',
      args: {
        preferenceType: prefType,
        preferenceValue: userInput,
      },
    };
  }

  return null;
}
