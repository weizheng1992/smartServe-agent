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
    return /(?:加购物车|加入购物车|放进购物车|加购|购物车|结算|买第|件加入|款加入|放入购物车|第[一二三四五12345两几][件款个双]|买第|要第|删除|移除|删掉|清空|改成\s*\d+|修改为\s*\d+|数量设为\s*\d+)/i.test(
      input,
    );
  }

  public async execute(context: SkillExecutionContext): Promise<SkillExecutionResult> {
    const input = (context.input || '').trim();
    const guideContext = (context.extra?.guideContext as ShoppingGuideContext) || {};
    const existingCart = (context.extra?.cartContext as CartContext) || {};

    // 1. 查看购物车与算价结算 (View Cart & Settlement)
    const isViewOnly =
      /(?:查看购物车|看下购物车|购物车总价|看购物车|购物车里|购物车有什么|多少钱|算下总价|结算|去买单|去结算)/i.test(
        input,
      ) && !/(?:加购物车|加入购物车|放进购物车|放入购物车|加购|买第|要第|改成|修改|删除|移除|删掉)/i.test(input);

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
        type: 'cart_card',
        data: {
          actionType: 'view',
          title: `购物车明细 (${cartData.totalQuantity || (cartData.items || []).length} 件)`,
          totalQuantity: cartData.totalQuantity || (cartData.items || []).length,
          totalAmount: cartData.payableAmount || cartData.totalAmount || 0,
          currency: 'CNY',
          items: (cartData.items || []).map((i: any) => ({
            id: i.skuId || i.id,
            skuId: i.skuId || i.id,
            title: i.title || i.name,
            price: Number(i.price || 0),
            quantity: Number(i.quantity || 1),
            imageUrl: i.imageUrl,
            specSummary: i.specSummary,
          })),
          actions: [
            { label: '去结算', action: 'checkout_cart' },
            { label: '清空购物车', action: 'clear_cart' },
          ],
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
          guideContext,
        },
      };
    }

    // 2. 购物车商品删除与清空 (Delete or Clear Cart)
    const isDelete =
      /(?:删除|移除|删掉|去掉|不要了|清空)/i.test(input) &&
      !/(?:加购物车|加入购物车|放进购物车|放入购物车|加购)/i.test(input);

    if (isDelete) {
      const summaryRes = await MallDomainService.getCartSummary({
        userId: context.userId,
        threadId: context.threadId,
      });
      const currentItems: any[] = (summaryRes.cart as any)?.items || existingCart.items || [];

      if (/(?:清空|全部删除|全删)/i.test(input)) {
        for (const item of currentItems) {
          await MallDomainService.updateCartItem({
            skuId: item.skuId,
            quantity: 0,
            userId: context.userId,
            threadId: context.threadId,
          });
        }
        return {
          success: true,
          skillId: this.metadata.id,
          output: '已成功清空购物车中的所有商品。如需重新选购，请随时告诉我！🛒',
          nextAction: 'finish',
          extra: {
            cartContext: { items: [], totalAmount: 0 },
            guideContext,
          },
        };
      }

      const ordinalMatch = input.match(/(?:把)?第\s*([一二三四五12345两])\s*[件款个双]?/);
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

      let targetItem = null;
      if (ordinalMatch) {
        const targetIndex = indexMap[ordinalMatch[1]] ?? 0;
        targetItem = currentItems[targetIndex];
      } else if (existingCart.lastModifiedItemId) {
        targetItem = currentItems.find((i) => i.skuId === existingCart.lastModifiedItemId);
      }
      if (!targetItem && currentItems.length > 0) {
        targetItem = currentItems[0];
      }

      if (targetItem) {
        const updateRes = await MallDomainService.updateCartItem({
          skuId: targetItem.skuId,
          quantity: 0,
          userId: context.userId,
          threadId: context.threadId,
        });
        const updatedCart = (updateRes.cart as any) || {};
        return {
          success: true,
          skillId: this.metadata.id,
          output: `🗑️ 已成功将【${targetItem.title}】从购物车中移除！\n当前购物车共有 ${updatedCart.totalQuantity || 0} 件商品，总金额 ¥${updatedCart.totalAmount || 0} 元。`,
          nextAction: 'finish',
          extra: {
            cartContext: {
              lastModifiedItemId: undefined,
              items: updatedCart.items,
              totalAmount: updatedCart.totalAmount,
            },
            guideContext,
          },
        };
      }

      return {
        success: true,
        skillId: this.metadata.id,
        output: '购物车中暂无该商品或已为空，无需重复移除。',
        nextAction: 'finish',
        extra: { guideContext, cartContext: existingCart },
      };
    }

    // 3. 数量修改 (Update Quantity)
    const updateMatch = input.match(/(?:改成|修改为|数量设为|变成|改为|调整为|增加到|减少到)\s*(\d+)\s*件?/);
    if (updateMatch && updateMatch[1]) {
      const newQty = Number(updateMatch[1]);
      const summaryRes = await MallDomainService.getCartSummary({
        userId: context.userId,
        threadId: context.threadId,
      });
      const currentItems: any[] = (summaryRes.cart as any)?.items || existingCart.items || [];

      const ordinalMatch = input.match(/(?:把)?第\s*([一二三四五12345两])\s*[件款个双]?/);
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

      let targetItem = null;
      if (ordinalMatch) {
        const targetIndex = indexMap[ordinalMatch[1]] ?? 0;
        targetItem = currentItems[targetIndex];
      } else if (existingCart.lastModifiedItemId) {
        targetItem = currentItems.find((i) => i.skuId === existingCart.lastModifiedItemId);
      }
      if (!targetItem && currentItems.length > 0) {
        targetItem = currentItems[0];
      }

      const targetSku = targetItem?.skuId || existingCart.lastModifiedItemId || 'sku_nike_aj1_blk_425';
      const updateRes = await MallDomainService.updateCartItem({
        skuId: targetSku,
        quantity: newQty,
        userId: context.userId,
        threadId: context.threadId,
      });

      const updatedCart = (updateRes.cart as any) || {};

      return {
        success: true,
        skillId: this.metadata.id,
        output: `✏️ 已成功将【${targetItem?.title || '商品'}】数量调整为 ${newQty} 件！\n当前购物车共有 ${updatedCart.totalQuantity || newQty} 件商品，总金额 ¥${updatedCart.totalAmount || 0} 元。`,
        nextAction: 'finish',
        extra: {
          cartContext: {
            lastModifiedItemId: targetSku,
            items: updatedCart.items,
            totalAmount: updatedCart.totalAmount,
          },
          guideContext,
        },
      };
    }

    // 3. 用户直接发送问句/复制提示词："把第几件加入购物车"
    const isVagueOrdinal = /(?:第几|哪件|哪款|哪一个)/i.test(input);
    if (isVagueOrdinal) {
      const candidates = guideContext.candidateProducts || [];
      if (candidates.length > 0) {
        const listText = candidates.map((c, i) => `${i + 1}. 【${c.name}】 ¥${c.price}`).join('\n');
        return {
          success: true,
          skillId: this.metadata.id,
          output: `请问您想将哪一款推荐商品加入购物车呢？\n\n${listText}\n\n您可以直接对我说“把第1件加入购物车”或“把第2件加入购物车”，我立即为您办理！🛒`,
          nextAction: 'finish',
          extra: { guideContext, cartContext: existingCart },
        };
      }
      return {
        success: true,
        skillId: this.metadata.id,
        output:
          '请问您想将哪一款商品加入购物车呢？您可以直接对我说“把第1件加入购物车”或“把第2件加入购物车”，我立即为您办理！🛒',
        nextAction: 'finish',
        extra: { guideContext, cartContext: existingCart },
      };
    }

    // 4. 加购执行 (Add To Cart & Cross-Agent Coreference Resolution)
    let targetSkuId = (context.slots?.skuId as string) || (context.slots?.productId as string) || '';
    let targetTitle = '精选推荐商品';
    let targetPrice = 899.0;

    let candidateProducts = guideContext.candidateProducts || [];
    let candidateList = guideContext.candidateProductIds || [];

    // 若 guideContext 为空，尝试从近期对话历史中智能回溯已推荐商品候选列表
    const shortMem = (context.extra?.shortMemory as any[]) || [];
    if (candidateList.length === 0 && shortMem.length > 0) {
      for (let i = shortMem.length - 1; i >= 0; i--) {
        const msg = shortMem[i];
        if (msg.role === 'assistant' && typeof msg.content === 'string' && msg.content.includes('推荐商品')) {
          const itemRegex = /(\d+)\.\s*【([^】]+)】\s*¥?(\d+(?:\.\d+)?)/g;
          let match: RegExpExecArray | null;
          const parsedProducts: Array<{
            id: string;
            name: string;
            price: number;
          }> = [];
          while ((match = itemRegex.exec(msg.content)) !== null) {
            parsedProducts.push({
              id: `prod_recommend_${match[1]}`,
              name: match[2],
              price: Number(match[3]),
            });
          }
          if (parsedProducts.length > 0) {
            candidateProducts = parsedProducts;
            candidateList = parsedProducts.map((p) => p.id);
            break;
          }
        }
      }
    }

    // 指代消解 (Coreference Resolution): 例如 "把第2件加入购物车", "买第一款", "第1件", "把第一款买了"
    const ordinalMatch = input.match(
      /(?:把)?第\s*([一二三四五12345两])\s*[件款个双]|买第\s*([一二三四五12345两])|第\s*([一二三四五12345两])\s*款/,
    );
    if (ordinalMatch) {
      const ordinalChar = ordinalMatch[1] || ordinalMatch[2] || ordinalMatch[3];
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
      if (candidateProducts[targetIndex]) {
        const prod = candidateProducts[targetIndex];
        targetSkuId = prod.id;
        targetTitle = prod.name;
        targetPrice = prod.price || 899.0;
      } else if (candidateList[targetIndex]) {
        targetSkuId = candidateList[targetIndex];
        targetTitle = `推荐商品 #${targetIndex + 1} (${targetSkuId})`;
      }
    }

    if (!targetSkuId) {
      if (candidateProducts.length > 0) {
        const prod = candidateProducts[0];
        targetSkuId = prod.id;
        targetTitle = prod.name;
        targetPrice = prod.price || 899.0;
      } else if (candidateList.length > 0) {
        targetSkuId = candidateList[0];
        targetTitle = `推荐商品 #1 (${targetSkuId})`;
      } else {
        // 默认兜底添加热销款
        targetSkuId = 'prod_nike_air_pegasus_41';
        targetTitle = 'Nike Air Zoom Pegasus 41 极速轻量透气跑鞋';
        targetPrice = 899.0;
      }
    }

    const qtyMatch = input.match(/(?:数量|买|要|加|购)\s*(\d+)\s*件?/);
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
      type: 'cart_card',
      data: {
        actionType: 'added',
        title: `已加入购物车: ${targetTitle}`,
        totalQuantity: updatedCart.totalQuantity || quantity,
        totalAmount: updatedCart.totalAmount || targetPrice * quantity,
        currency: 'CNY',
        items:
          updatedCart.items && updatedCart.items.length > 0
            ? updatedCart.items.map((it: any) => ({
                id: it.skuId || it.id,
                skuId: it.skuId || it.id,
                title: it.title || it.name || targetTitle,
                price: Number(it.price || targetPrice),
                quantity: Number(it.quantity || quantity),
                imageUrl: it.imageUrl,
                specSummary: it.specSummary,
              }))
            : [
                {
                  id: targetSkuId,
                  skuId: targetSkuId,
                  title: targetTitle,
                  price: targetPrice,
                  quantity,
                },
              ],
        actions: [
          { label: '去结算', action: 'checkout_cart' },
          { label: '查看购物车', action: 'view_cart' },
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
      extra: {
        cartContext: newCartContext,
        guideContext: {
          ...guideContext,
          candidateProductIds: candidateList,
          candidateProducts,
        },
      },
    };
  }
}
