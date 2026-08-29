import type { SkillExecutionContext, SkillExecutionResult, SkillMetadata } from 'types';
import { BaseSkill } from './baseSkill';

export class ProductInquirySkill extends BaseSkill {
  public metadata: SkillMetadata = {
    id: 'skill_product_inquiry',
    name: '商品导购与现货库存查询 SOP',
    description: '穿透查询第三方商品目录、实时 SKU 现货库存及商品推荐',
    category: 'pre_sale',
    triggerIntents: ['PRODUCT_INQUIRY', 'product_query', 'general_query', 'mall_search'],
    requiredTools: ['searchProducts'],
    version: '1.0.0',
  };

  public async execute(context: SkillExecutionContext): Promise<SkillExecutionResult> {
    const query = (context.slots?.query as string) || context.input || '';
    const category = (context.slots?.category as string) || undefined;

    const spiClient = await this.getSpiClient(context.tenantId);
    const products = await spiClient.searchProducts({
      query,
      category,
      tenantId: context.tenantId,
      limit: 3,
    });

    if (!products || products.length === 0) {
      return {
        success: true,
        skillId: this.metadata.id,
        output: `抱歉，未能找到与“${query}”相关的商品，您可以尝试更换关键词或咨询在线客服。`,
        nextAction: 'finish',
      };
    }

    const productSummary = products
      .map((p) => {
        let text = `• 【${p.title}】 (¥${p.price}) - 总库存: ${p.stock > 0 ? `${p.stock}件现货` : '暂时缺货'}`;
        if (p.specDimensions && p.specDimensions.length > 0) {
          const dims = p.specDimensions.map((d) => `${d.name}: ${d.values.join('/')}`).join(' | ');
          text += `\n   📐 可选规格: ${dims}`;
        }
        if (p.specs && Object.keys(p.specs).length > 0) {
          const specEntries = Object.entries(p.specs)
            .slice(0, 2)
            .map(([k, v]) => `${k}:${v}`)
            .join('；');
          text += `\n   🔬 核心参数: ${specEntries}`;
        }
        return text;
      })
      .join('\n\n');

    return {
      success: true,
      skillId: this.metadata.id,
      output: `为您找到以下相关商品：\n${productSummary}\n\n如需了解具体尺码规格或下单，请随时告诉我！`,
      nextAction: 'finish',
    };
  }
}
