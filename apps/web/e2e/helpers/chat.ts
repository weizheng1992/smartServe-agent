import type { Locator, Page } from '@playwright/test';

/**
 * 主聊天消息区定位器(共享):侧栏与 APM 面板同样用 overflow-y-auto,
 * 必须以 p-6 锚定真正的主聊天滚动容器 —— 各 spec 曾各自内联同一选择器,
 * 改版时容易只改一处(wayfinder 004 评审提取)。
 */
export function chatContainer(page: Page): Locator {
  return page.locator('div.overflow-y-auto.p-6');
}
