import { MallDomainService } from 'tools';
import type {
  CartContext,
  RichCardBlock,
  ShoppingGuideContext,
  SkillExecutionContext,
  SkillExecutionResult,
  SkillMetadata,
} from 'types';
import { BaseSkill } from './baseSkill';

export class CartManageSkill extends BaseSkill {
  public metadata: SkillMetadata = {
    id: 'skill_cart_manage',
    name: '交易与购物车管理 Agent SOP',
    description: '参数核验、加购、商品规格变更、购物车结算与优惠汇总',
    category: 'in_sale',
    triggerIntents: ['cart_manage', 'cart_add', 'cart_update'],
    requiredTools: ['addToCart', 'getCartSummary', 'updateCartItem'],
    version: '1.0.0',
  };

  public canHandle(context: SkillExecutionContext): boolean {
    const intent = (context.slots?.activeIntent as string) || (context.extra?.intent as string) || '';
    if (this.metadata.triggerIntents.includes(intent)) return true;
    const input = (context.input || '').toLowerCase();
    return /(?:加购物车|加入购物车|放进购物车|加购|购物车|结算|买第|件加入|放入购物车)/i.test(input);
  }

  public async execute(context: SkillExecutionContext): Promise<SkillExecutionResult> {
    const input = (context.input || '').trim();
    const guideContext = (context.extra?.guideContext as ShoppingGuideContext) || {};
    const existingCart = (context.extra?.cartContext as CartContext) || {};

    // 1. 查看购物车与算价结算 (View Cart & Settlement)
    const isViewOnly =
      /(?:查看购物车|看下购物车|购物车里|购物车有什么|多少钱|算下总价|结算|去买单)/i.test(input) &&
      !/(?:加|买|放)/i.test(input);

    if (isViewOnly) {
      const summaryRes = await MallDomainService.getCartSummary({
        userId: context.userId,
        threadId: context.threadId,
      });

      const cartData = (summaryRes.cart as any) || {
        items: [],
        totalAmount: 0,
      };
      const card: RichCardBlock = {
        type: 'order_card',
        data: {
          orderId: 'CART-PREVIEW',
          status: '购物车结算预估',
          totalAmount: cartData.payableAmount || cartData.totalAmount || 0,
          currency: 'CNY',
          items: (cartData.items || []).map((i: any) => ({
            id: i.skuId || i.id,
            title: i.title || i.name,
            price: Number(i.price || 0),
            quantity: Number(i.quantity || 1),
            imageUrl: i.imageUrl,
          })),
        },
      };

      const itemsText = (cartData.items || [])
        .map((i: any, idx: number) => `${idx + 1}. ${i.title} x${i.quantity} (¥${i.price})`)
        .join('\n');

      return {
        success: true,
        skillId: this.metadata.id,
        output: `您的购物车目前共有 ${cartData.totalQuantity || 0} 件商品：\n\n${itemsText || '（暂无商品）'}\n\n💰 商品总价: ¥${cartData.totalAmount || 0}元\n🎁 预估优惠: -¥${cartData.discount || 0}元\n💵 实付预估: ¥${cartData.payableAmount || 0}元`,
        cards: [card],
        nextAction: 'finish',
        extra: {
          cartContext: {
            items: cartData.items,
            totalAmount: cartData.totalAmount,
          },
        },
      };
    }

    // 2. 数量修改与移除 (Update or Remove)
    const updateMatch = input.match(/(?:改成|修改为|数量设为|变成|改为)\s*(\d+)\s*件?/);
    if (updateMatch && updateMatch[1]) {
      const newQty = Number(updateMatch[1]);
      const targetSku = existingCart.lastModifiedItemId || 'sku_nike_aj1_blk_425';
      const updateRes = await MallDomainService.updateCartItem({
        skuId: targetSku,
        quantity: newQty,
        userId: context.userId,
        threadId: context.threadId,
      });

      return {
        success: true,
        skillId: this.metadata.id,
        output: updateRes.message || `已成功将商品数量调整为 ${newQty} 件。`,
        nextAction: 'finish',
      };
    }

    // 3. 加购执行 (Add To Cart & Cross-Agent Coreference Resolution)
    let targetSkuId = (context.slots?.skuId as string) || (context.slots?.productId as string) || '';
    let targetTitle = '精选推荐商品';
    const targetPrice = 899.0;

    // 指代消解 (Coreference Resolution): 例如 "把第2件加入购物车", "买第一款"
    const ordinalMatch = input.match(/第\s*([一二三四五12345两])\s*[件款个双双]/);
    if (ordinalMatch && ordinalMatch[1]) {
      const ordinalChar = ordinalMatch[1];
      const indexMap: Record<string, number> = {
        一: 0,
        '1': 0,
        二: 1,
        '2': 1,
        两: 1,
        三: 2,
        '3': 2,
        四: 3,
        '4': 3,
        五: 4,
        '5': 4,
      };
      const targetIndex = indexMap[ordinalChar] ?? 0;
      const candidateList = guideContext.candidateProductIds || [];
      if (candidateList[targetIndex]) {
        targetSkuId = candidateList[targetIndex];
        targetTitle = `推荐商品 #${targetIndex + 1} (${targetSkuId})`;
      }
    }

    if (!targetSkuId) {
      // 默认兜底添加热销款
      targetSkuId = guideContext.candidateProductIds?.[0] || 'prod_nike_air_pegasus_41';
      targetTitle = 'Nike Air Zoom Pegasus 41 极速轻量透气跑鞋';
    }

    const qtyMatch = input.match(/(?:数量|买|要|加)\s*(\d+)\s*件?/);
    const quantity = qtyMatch && qtyMatch[1] ? Number(qtyMatch[1]) : 1;

    const addRes = await MallDomainService.addToCart({
      skuId: targetSkuId,
      quantity,
      title: targetTitle,
      price: targetPrice,
      userId: context.userId,
      threadId: context.threadId,
    });

    const updatedCart = (addRes.cart as any) || {};

    const card: RichCardBlock = {
      type: 'order_card',
      data: {
        orderId: 'CART-ADDED',
        status: '已加入购物车',
        totalAmount: updatedCart.totalAmount || targetPrice * quantity,
        currency: 'CNY',
        items: [
          {
            id: targetSkuId,
            title: targetTitle,
            price: targetPrice,
            quantity,
          },
        ],
      },
    };

    const newCartContext: CartContext = {
      lastModifiedItemId: targetSkuId,
      items: updatedCart.items,
      totalAmount: updatedCart.totalAmount,
    };

    return {
      success: true,
      skillId: this.metadata.id,
      output: `🎉 已成功将【${targetTitle}】(x${quantity}) 加入购物车！\n当前购物车共有 ${updatedCart.totalQuantity || quantity} 件商品，总金额 ¥${updatedCart.totalAmount || targetPrice * quantity} 元。\n\n如需结算买单或调整数量，请随时告诉我！`,
      cards: [card],
      nextAction: 'finish',
      extra: { cartContext: newCartContext },
    };
  }
}
