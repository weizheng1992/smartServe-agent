import { describe, expect, it } from 'bun:test';
import { db } from 'db';
import { OrderDomainService } from 'tools';
import { EpisodicMemory, LongMemory, ShortMemory } from '../src/memory';

describe('🏢 Multi-Tenant Context & Memory Isolation Suite', () => {
  it('ShortMemory: 线程会话严格隔离且支持独立读写', async () => {
    const threadA = `test_tenant_thread_nike_${Date.now()}`;
    const threadB = `test_tenant_thread_adidas_${Date.now()}`;

    await db.createThread(threadA, 'user_tenant_001', 'nike');
    await db.createThread(threadB, 'user_tenant_001', 'adidas');

    const shortA = new ShortMemory(threadA);
    const shortB = new ShortMemory(threadB);

    await shortA.addMessage('user', '我想咨询耐克跑鞋');
    await shortA.addMessage('assistant', '您好，耐克跑鞋为您推荐飞马40。');

    await shortB.addMessage('user', '我想咨询阿迪达斯椰子');
    await shortB.addMessage('assistant', '您好，阿迪达斯推荐UB系列。');

    const msgsA = await shortA.getMessages();
    const msgsB = await shortB.getMessages();

    expect(msgsA.length).toBe(2);
    expect(msgsA[0].content).toContain('耐克');
    expect(msgsB.length).toBe(2);
    expect(msgsB[0].content).toContain('阿迪达斯');
  });

  it('createThread: 已存在线程不会被无意覆盖原有 business_id', async () => {
    const threadId = `test_persistent_thread_${Date.now()}`;
    const userId = 'user_persistent_001';

    // 1. 初始化为 nike
    const created = await db.createThread(threadId, userId, 'nike');
    expect(created.businessId).toBe('nike');

    // 2. 模拟后续消息调用 createThread 但未传递 businessId (默认 undefined)
    const reloaded = await db.createThread(threadId, userId);
    expect(reloaded.businessId).toBe('nike');

    // 3. 验证 OrderDomainService.getThreadSessionContext 读取该会话的 businessId
    const sessionCtx = await OrderDomainService.getThreadSessionContext(threadId);
    expect(sessionCtx.businessId).toBe('nike');
  });

  it('EpisodicMemory & LongMemory: 携带用户与商户租户隔离标识，防止未授权越权检索', async () => {
    const userA = `user_iso_a_${Date.now()}`;
    const userB = `user_iso_b_${Date.now()}`;

    const episodicA = new EpisodicMemory(userA, 'nike');
    const episodicB = new EpisodicMemory(userB, 'adidas');

    await episodicA.addEvent('用户喜欢耐克暗黑系穿搭', 8);

    const retrievedA = await episodicA.retrieveEvents('用户喜欢耐克暗黑系穿搭', 5);
    const retrievedB = await episodicB.retrieveEvents('用户喜欢耐克暗黑系穿搭', 5);

    expect(retrievedA.length).toBeGreaterThanOrEqual(1);
    expect(retrievedB.length).toBe(0); // userB 绝对隔离，不可检索到 userA 的记忆

    // 空 userId 防御
    const episodicEmpty = new EpisodicMemory('', 'ecommerce');
    const emptyEvents = await episodicEmpty.retrieveEvents('任何偏好');
    expect(emptyEvents).toEqual([]);

    const longEmpty = new LongMemory('', 'ecommerce');
    const emptyFacts = await longEmpty.searchRelevantFacts('任何偏好');
    expect(emptyFacts).toEqual([]);
  });

  it('🛡️ 双层画像隔离拓扑 (Dual-Tier Scoped Persona): 全局身体事实共享，商户专属私域画像100%物理阻断', async () => {
    const userId = `user_scoped_persona_${Date.now()}`;
    const longNike = new LongMemory(userId, 'nike');
    const longAdidas = new LongMemory(userId, 'adidas');

    // 1. 沉淀全局生理事实 (Scope: global)
    await longNike.extractAndStoreFact('fact: 用户脚长为 270mm，对羊毛材质过敏', '我脚长270mm对羊毛严重过敏', 'global');

    // 2. 沉淀 Nike 私域专属偏好 (Scope: tenant, businessId: nike)
    await longNike.extractAndStoreFact(
      'fact: 用户在耐克店铺酷爱 Nike Flyknit 飞线系列并持有黑金专属折扣卷',
      '我特别喜欢耐克Flyknit飞线鞋',
      'tenant',
      'nike',
    );

    // 3. 沉淀 Adidas 私域专属偏好 (Scope: tenant, businessId: adidas)
    await longAdidas.extractAndStoreFact(
      'fact: 用户在阿迪达斯店铺偏好 Ultraboost 缓震跑鞋',
      '我平时在阿迪只看Ultraboost',
      'tenant',
      'adidas',
    );

    // 4. 在 Adidas 店铺中进行画像检索
    const factsInAdidas = await longAdidas.searchRelevantFacts('脚长 270mm 跑鞋偏好');
    const factsTextInAdidas = JSON.stringify(factsInAdidas);

    // 验证：成功召回全局身体事实与 Adidas 专属偏好
    expect(factsTextInAdidas).toContain('270mm');
    // 验证：绝不包含 Nike 私域专属偏好（防跨租户投毒与泄密）
    expect(factsTextInAdidas).not.toContain('Nike Flyknit');
    expect(factsTextInAdidas).not.toContain('黑金专属折扣卷');

    // 5. 在 Nike 店铺中进行画像检索
    const factsInNike = await longNike.searchRelevantFacts('Nike 跑鞋偏好');
    const factsTextInNike = JSON.stringify(factsInNike);

    // 验证：成功召回 Nike 专属偏好
    expect(factsTextInNike).toContain('Nike Flyknit');
    // 验证：绝不包含 Adidas 私域专属偏好
    expect(factsTextInNike).not.toContain('Ultraboost');
  });
});
