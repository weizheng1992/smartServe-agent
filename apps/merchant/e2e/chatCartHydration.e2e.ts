import { expect, test } from '@playwright/test';

// 商城车 × 引擎车水合回归(2026-09-14 用户报告:商城页明明有商品,对客服说
// 「删除购物车的商品」却回复"购物车还是空的,没有可移除的商品")。
//
// 成因面:商城 UI 加购只写 localStorage(aurora_store_cart),引擎购物车在
// Redis(agent:cart:{userId}),两条存储互不相通 —— 客服视角永远空车。
// 本 spec 钉用户完整流:先经客服清空保证引擎车起点确定,再商城页真实加购,
// 然后下删除指令 —— 修复后引擎车应水合商城车并真实删除,购物车页随之清空。
// 「删除.*?购物车」走 triage 快轨(CartManageSkill),零 LLM,全程确定性。

test.use({ baseURL: 'http://localhost:3005' });

test.describe('💬 商城车 × 引擎车水合', () => {
  test('商城加购后客服删除,必须操作真实车,不得谎报空车', async ({ page }) => {
    test.setTimeout(120_000);
    const input = page.getByPlaceholder('请输入您的问题或指令...');
    const openChat = async () => {
      await page.locator("button:has-text('极光智能客服')").click();
      // 开新对话:悬浮窗按 thread 恢复历史,旧回复(含历次失败文案)会污染
      // 对话区全文断言 —— 断言只针对本次新对话的消息
      const newChatBtn = page.locator("button[title='开启新对话']");
      if (await newChatBtn.isVisible().catch(() => false)) {
        await newChatBtn.click();
      }
      return page.locator("div.fixed:has-text('极光潮品 AI 智能助理')");
    };

    await page.goto('/');
    await page.evaluate(() => localStorage.removeItem('aurora_store_cart'));

    // 引擎车起点确定性:先经客服清空(引擎侧若有历史残留一并清掉)
    let chatModal = await openChat();
    await input.fill('清空购物车');
    await input.press('Enter');
    await expect(chatModal).toContainText(/购物车|清空/, { timeout: 90_000 });

    // 商城页真实加购(只写商城车,引擎车不知情 —— 今日症状的成因面)
    await page.goto('/products/SPU-AURORA-001');
    await page.locator("button:has-text('加入购物车')").click();
    await expect(page.locator('body')).toContainText('已成功加入购物车');

    // 对客服下删除指令:今日红线 —— 「购物车还是空的,没有可移除的商品」;
    // 等待移除回复落地(新对话区干净,not 断言会瞬时假通过,必须等正向信号)
    chatModal = await openChat();
    await input.fill('删除购物车的商品');
    await input.press('Enter');
    await expect(chatModal).toContainText('已成功将', { timeout: 90_000 });
    await expect(chatModal).not.toContainText('没有可移除的商品');

    // 引擎车变更应经 cart_card 快照回同步商城车:localStorage 已剔除该商品
    const storedAfter = (await page.evaluate(() => localStorage.getItem('aurora_store_cart'))) ?? '';
    const cleared = storedAfter === '' || storedAfter === '[]' || !storedAfter.includes('SPU-AURORA-001');
    expect(cleared, `聊天删除必须回同步商城车,实际: ${storedAfter.slice(0, 120)}`).toBe(true);

    // 产品级闭环:购物车页随之清空
    await page.goto('/cart');
    await expect(page.locator('body')).toContainText('购物车空空如也');
  });
});
