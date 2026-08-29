'use client';

import React, { useEffect, useRef, useState } from 'react';
import type { InteractiveProductCardData, ProductSkuSpec } from 'types';
import { CheckCircle2, Minus, Plus, ShoppingCart, Zap } from '../../icons';

export interface InteractiveProductCardProps {
  data: InteractiveProductCardData;
  onAction?: (action: string, payload?: Record<string, unknown>) => void;
}

export const InteractiveProductCard: React.FC<InteractiveProductCardProps> = ({ data, onAction }) => {
  const skus = data.skus || [];
  const [selectedSkuId, setSelectedSkuId] = useState<string>(data.selectedSkuId || (skus[0]?.skuId ?? ''));
  const [quantity, setQuantity] = useState<number>(data.selectedQuantity || 1);
  const [isAdded, setIsAdded] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
      }
    };
  }, []);

  const currentSku: ProductSkuSpec | undefined = skus.find((s) => s.skuId === selectedSkuId) || skus[0];
  const unitPrice = currentSku ? currentSku.price : data.basePrice;
  const totalPrice = unitPrice * quantity;
  const displayImage = currentSku?.imageUrl || data.imageUrl;

  const handleAddToCart = () => {
    if (!currentSku) return;
    setIsAdded(true);
    onAction?.('add_to_cart_interactive', {
      productId: data.productId,
      skuId: currentSku.skuId,
      skuTitle: currentSku.title,
      price: currentSku.price,
      quantity,
      title: data.title,
      imageUrl: displayImage,
    });
    timerRef.current = setTimeout(() => {
      setIsAdded(false);
    }, 1500);
  };

  const handleDirectBuy = () => {
    if (!currentSku) return;
    onAction?.('buy_now_interactive', {
      productId: data.productId,
      skuId: currentSku.skuId,
      skuTitle: currentSku.title,
      price: currentSku.price,
      quantity,
      title: data.title,
      imageUrl: displayImage,
    });
  };

  return (
    <div className="my-2 max-w-md overflow-hidden rounded-xl border border-sky-800/40 bg-gradient-to-b from-slate-900 via-slate-850 to-slate-900 p-4 text-slate-100 shadow-xl backdrop-blur-md transition-all hover:border-sky-600/60">
      {/* Product Main Preview */}
      <div className="flex gap-3.5">
        {displayImage ? (
          <img
            src={displayImage}
            alt={data.title}
            className="h-20 w-20 rounded-lg object-cover border border-slate-700/60 shrink-0 bg-slate-800"
          />
        ) : (
          <div className="h-20 w-20 rounded-lg bg-slate-800 border border-slate-700/60 flex items-center justify-center text-slate-500 shrink-0">
            <ShoppingCart className="h-8 w-8" />
          </div>
        )}

        <div className="flex-1 min-w-0">
          <div className="text-xs font-semibold text-sky-400">热销精选推荐</div>
          <h4 className="text-sm font-bold text-slate-100 truncate">{data.title}</h4>
          {data.subtitle && <p className="text-[11px] text-slate-400 line-clamp-1 mt-0.5">{data.subtitle}</p>}

          <div className="mt-1 flex items-baseline gap-1.5">
            <span className="text-xs text-slate-400">单价:</span>
            <span className="font-mono text-base font-extrabold text-sky-300">¥{unitPrice.toFixed(2)}</span>
            {currentSku && currentSku.stock <= 5 && (
              <span className="text-[10px] text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded border border-amber-500/20">
                仅剩 {currentSku.stock} 件
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Sku Specifications Selector */}
      {skus.length > 0 && (
        <div className="mt-3 pt-3 border-t border-slate-800/80">
          <span className="text-xs text-slate-400">选择规格:</span>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {skus.map((sku) => {
              const isSelected = sku.skuId === selectedSkuId;
              return (
                <button
                  key={sku.skuId}
                  type="button"
                  onClick={() => setSelectedSkuId(sku.skuId)}
                  className={`rounded-lg px-2.5 py-1 text-xs transition-all cursor-pointer border ${
                    isSelected
                      ? 'bg-sky-500/20 border-sky-400 text-sky-200 font-medium shadow-xs'
                      : 'bg-slate-800/60 border-slate-700/60 text-slate-300 hover:border-slate-500'
                  }`}
                >
                  {sku.title || `${sku.color || ''} ${sku.size || ''}`.trim() || sku.skuId}
                  <span className="ml-1 font-mono text-[10px] opacity-75">¥{sku.price}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Quantity & Total Price */}
      <div className="mt-3 flex items-center justify-between border-t border-slate-800/80 pt-3">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">购买数量:</span>
          <div className="flex items-center rounded-lg border border-slate-700 bg-slate-800/80 p-0.5">
            <button
              type="button"
              disabled={quantity <= 1}
              onClick={() => setQuantity((q) => Math.max(1, q - 1))}
              className="flex h-6 w-6 items-center justify-center rounded-md text-slate-300 hover:bg-slate-700 disabled:opacity-40 cursor-pointer"
            >
              <Minus className="h-3 w-3" />
            </button>
            <span className="w-8 text-center font-mono text-xs font-semibold text-slate-100">{quantity}</span>
            <button
              type="button"
              disabled={currentSku ? quantity >= currentSku.stock : false}
              onClick={() => setQuantity((q) => q + 1)}
              className="flex h-6 w-6 items-center justify-center rounded-md text-slate-300 hover:bg-slate-700 disabled:opacity-40 cursor-pointer"
            >
              <Plus className="h-3 w-3" />
            </button>
          </div>
        </div>

        <div className="text-right">
          <span className="text-[11px] text-slate-400">小计: </span>
          <span className="font-mono text-base font-extrabold text-sky-300">¥{totalPrice.toFixed(2)}</span>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="mt-3 flex gap-2 border-t border-slate-800/80 pt-3">
        <button
          type="button"
          onClick={handleAddToCart}
          className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition-all cursor-pointer ${
            isAdded
              ? 'bg-emerald-600 text-white'
              : 'bg-slate-800 text-sky-300 hover:bg-slate-750 border border-sky-800/50'
          }`}
        >
          {isAdded ? <CheckCircle2 className="h-3.5 w-3.5" /> : <ShoppingCart className="h-3.5 w-3.5" />}
          {isAdded ? '已加入购物车' : '加入购物车'}
        </button>

        <button
          type="button"
          onClick={handleDirectBuy}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-sky-600 px-3 py-2 text-xs font-semibold text-white shadow-sm hover:bg-sky-500 cursor-pointer"
        >
          <Zap className="h-3.5 w-3.5" />
          立即结算
        </button>
      </div>
    </div>
  );
};
