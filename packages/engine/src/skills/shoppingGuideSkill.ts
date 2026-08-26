import { MallDomainService } from 'tools';
import type {
  RichCardBlock,
  ShoppingGuideContext,
  SkillExecutionContext,
  SkillExecutionResult,
  SkillMetadata,
} from 'types';
import { BaseSkill } from './baseSkill';

export class ShoppingGuideSkill extends BaseSkill {
  public metadata: SkillMetadata = {
    id: 'skill_shopping_guide',
    name: '商品智能导购与选品推荐 Agent SOP',
    description: '多轮偏好挖掘、商品库深度检索、多维参数比对与候选集维护',
    category: 'pre_sale',
    triggerIntents: ['shopping_guide', 'general_query', 'product_query', 'PRODUCT_INQUIRY'],
    requiredTools: ['searchProducts', 'compareProducts', 'queryProductSkus'],
    version: '1.0.0',
  };

  public canHandle(context: SkillExecutionContext): boolean {
    const intent = (context.slots?.activeIntent as string) || (context.extra?.intent as string) || '';
    if (this.metadata.triggerIntents.includes(intent)) return true;
    const input = (context.input || '').toLowerCase();
    return /(?:推荐|买什么|挑一款|选一款|好看|款式|选鞋|选衣服|哪款好|跑步鞋|卫衣|夹克)/i.test(input);
  }

  public async execute(context: SkillExecutionContext): Promise<SkillExecutionResult> {
    const input = (context.input || '').trim();
    const existingGuide = (context.extra?.guideContext as ShoppingGuideContext) || {};
    const extractedPrefs: Record<string, string> = {
      ...(existingGuide.extractedPreferences || {}),
    };
    let clarificationRound = existingGuide.clarificationRound || 0;

    // 1. 偏好特征提取 (Preferences Extraction)
    if (/男|男生|男款/i.test(input)) extractedPrefs.gender = '男款';
    if (/女|女生|女款/i.test(input)) extractedPrefs.gender = '女款';
    if (/透气|清爽|夏/i.test(input)) extractedPrefs.feature = '透气轻便';
    if (/缓震|护膝|慢跑|马/i.test(input)) extractedPrefs.scenario = '专业缓震慢跑';
    if (/黑|白|红/i.test(input)) {
      const colorMatch = input.match(/(?:黑|白|红|蓝|灰)色?/);
      if (colorMatch) extractedPrefs.color = colorMatch[0];
    }

    const budgetMatch = input.match(/(?:预算|低于|不超过|最高|价位)\s*(\d+)/);
    let maxPrice: number | undefined;
    if (budgetMatch && budgetMatch[1]) {
      maxPrice = Number(budgetMatch[1]);
      extractedPrefs.budget = `¥${maxPrice}以内`;
    }

    // 2. 超模糊查询的多轮启发式追问 (Vague Query Clarification)
    const isVeryVague =
      input.length <= 4 &&
      !maxPrice &&
      !extractedPrefs.scenario &&
      !extractedPrefs.gender &&
      clarificationRound === 0 &&
      /(?:买东西|买鞋|买衣服|推荐|逛逛)/i.test(input);

    if (isVeryVague) {
      clarificationRound += 1;
      const guideContext: ShoppingGuideContext = {
        extractedPreferences: extractedPrefs,
        clarificationRound,
      };

      return {
        success: true,
        skillId: this.metadata.id,
        output:
          '您好！我是您的专属选品顾问。请问您这次选购是男款还是女款？主要用于日常通勤还是专业运动跑步呢？告诉我您的偏好或预算，我将为您精准挑选！✨',
        nextAction: 'finish',
        extra: { guideContext },
      };
    }

    // 3. 执行商品检索与推荐 (Search & Recommend)
    const searchRes = await MallDomainService.searchProducts({
      query: input,
      maxPrice,
      limit: 3,
      businessId: context.tenantId,
      threadId: context.threadId,
    });

    const products = (searchRes.products as any[]) || [];
    const candidateProductIds = products.map((p) => p.id);

    if (products.length === 0) {
      return {
        success: true,
        skillId: this.metadata.id,
        output: `抱歉，暂时未能找到完全符合“${input}”的现货商品。建议您可以调整预算或关键词再试一次！`,
        nextAction: 'finish',
      };
    }

    // 4. 组装商品卡片 (Product Cards)
    const cards: RichCardBlock[] = [
      {
        type: 'product_ranking',
        data: {
          rankingMetric: 'recommendation',
          metricLabel: '热销推荐',
          metricUnit: '分',
          itemCount: products.length,
          summary: `为您精选 ${products.length} 款现货商品`,
          products: products.map((p, idx) => ({
            rank: idx + 1,
            productId: p.id,
            name: p.name,
            category: p.category || '精选现货',
            price: Number(p.price || 0),
            stock: Number(p.stock || 0),
            totalVolume: Number(p.salesVolume || 100),
            totalGmv: Number(p.price || 0) * 100,
            grossProfit: Number(p.price || 0) * 0.4,
            marginRate: '40%',
            metricScore: 99 - idx * 5,
            metricDisplay: idx === 0 ? '热销推荐' : `推荐 No.${idx + 1}`,
          })),
        },
      },
    ];

    const productSummaryText = products
      .map((p, idx) => {
        let text = `${idx + 1}. 【${p.name}】 ¥${p.price} (现货 ${p.stock} 件)\n   💡 ${p.description}`;
        if (p.specs && Object.keys(p.specs).length > 0) {
          const specStr = Object.entries(p.specs)
            .map(([k, v]) => `${k}:${v}`)
            .join(' | ');
          text += `\n   📐 特点: ${specStr}`;
        }
        return text;
      })
      .join('\n\n');

    const prefSummary =
      Object.keys(extractedPrefs).length > 0 ? `（已结合您的偏好：${Object.values(extractedPrefs).join('、')}）` : '';

    const output = `为您精选了以下推荐商品${prefSummary}：\n\n${productSummaryText}\n\n如需加入购物车，直接对我说“把第几件加入购物车”即可！🛒`;

    const guideContext: ShoppingGuideContext = {
      candidateProductIds,
      candidateProducts: products.map((p) => ({
        id: p.id,
        name: p.name,
        price: Number(p.price || 0),
        stock: Number(p.stock || 0),
        description: p.description,
        specs: p.specs,
        imageUrl: p.imageUrl,
      })),
      extractedPreferences: extractedPrefs,
      clarificationRound: clarificationRound + 1,
      lastSearchQuery: input,
    };

    return {
      success: true,
      skillId: this.metadata.id,
      output,
      cards,
      nextAction: 'finish',
      extra: { guideContext },
    };
  }
}
