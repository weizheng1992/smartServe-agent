import type React from 'react';
import { Button, Checkbox, Sheet, SheetContent, SheetHeader, SheetTitle } from 'ui';
import type { CustomerAddress } from '../address/AddressModal';

export interface CartItem {
  id: string; // SKU code
  spuId: string;
  skuCode: string;
  title: string;
  skuTitle: string;
  imageUrl: string;
  price: number;
  originalPrice?: number;
  quantity: number;
  stock: number;
  specAttributes: Record<string, string>;
  selected: boolean;
}

interface CartDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  cart: CartItem[];
  onUpdateQuantity: (skuCode: string, delta: number) => void;
  onToggleSelect: (skuCode: string) => void;
  onToggleSelectAll: () => void;
  onRemoveItem: (skuCode: string) => void;
  onClearCart: () => void;
  selectedAddress: CustomerAddress | null;
  onOpenAddressModal: () => void;
  onCheckout: () => void;
  isCheckingOut: boolean;
}

export const CartDrawer: React.FC<CartDrawerProps> = ({
  isOpen,
  onClose,
  cart,
  onUpdateQuantity,
  onToggleSelect,
  onToggleSelectAll,
  onRemoveItem,
  selectedAddress,
  onOpenAddressModal,
  onCheckout,
  isCheckingOut,
}) => {
  const selectedItems = cart.filter((item) => item.selected);
  const isAllSelected = cart.length > 0 && selectedItems.length === cart.length;
  const totalPrice = selectedItems.reduce((sum, item) => sum + item.price * item.quantity, 0);
  const totalCount = selectedItems.reduce((sum, item) => sum + item.quantity, 0);

  return (
    <Sheet open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full max-w-md p-0 flex flex-col bg-white">
        {/* 抽屉顶部 Header */}
        <SheetHeader className="p-4 sm:p-5 border-b border-slate-200 bg-slate-50/80">
          <SheetTitle className="flex items-center space-x-2 text-lg font-bold text-slate-900">
            <span className="text-xl">🛒</span>
            <span>我的购物车 ({cart.length})</span>
          </SheetTitle>
        </SheetHeader>

        {/* 抽屉中间 内容区 */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-5 space-y-4">
          {/* 收货地址快捷确认栏 */}
          <div className="bg-emerald-50 border border-emerald-200/80 rounded-xl p-3.5 flex items-start justify-between gap-3">
            <div className="flex items-start space-x-2.5">
              <span className="text-emerald-600 text-lg mt-0.5">📍</span>
              <div>
                <div className="text-xs font-semibold text-emerald-900 flex items-center space-x-1.5">
                  <span>配送至：</span>
                  {selectedAddress ? (
                    <span>
                      {selectedAddress.recipientName} ({selectedAddress.phone})
                    </span>
                  ) : (
                    <span className="text-emerald-700 font-normal">未选择地址</span>
                  )}
                </div>
                <p className="text-xs text-emerald-800 mt-1 line-clamp-1">
                  {selectedAddress?.fullAddress || '请点击右侧选择或添加收货地址'}
                </p>
              </div>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onOpenAddressModal}
              className="text-xs font-medium text-emerald-700 hover:text-emerald-900 bg-white border-emerald-300 h-7 px-2.5"
            >
              切换
            </Button>
          </div>

          {/* 购物车条目列表 */}
          {cart.length === 0 ? (
            <div className="py-16 text-center text-slate-400">
              <div className="text-5xl mb-3">🛍️</div>
              <p className="text-sm font-medium text-slate-600">购物车空空如也</p>
              <p className="text-xs text-slate-400 mt-1">快去挑选心仪的潮品规格并加入购物车吧！</p>
            </div>
          ) : (
            <div className="space-y-3">
              {cart.map((item) => (
                <div
                  key={item.id}
                  className={`border rounded-xl p-3.5 flex items-start gap-3 transition ${
                    item.selected
                      ? 'border-emerald-500/80 bg-emerald-50/20 shadow-2xs'
                      : 'border-slate-200 bg-white opacity-80'
                  }`}
                >
                  {/* 单项复选框 */}
                  <div className="mt-3.5">
                    <Checkbox checked={item.selected} onCheckedChange={() => onToggleSelect(item.skuCode)} />
                  </div>

                  {/* 商品图片 */}
                  <img
                    src={item.imageUrl}
                    alt={item.title}
                    className="w-18 h-18 object-cover rounded-lg border border-slate-200 shrink-0 bg-slate-100"
                  />

                  {/* 商品详情与操作 */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-1">
                      <h4 className="text-xs font-bold text-slate-900 truncate">{item.title}</h4>
                      <button
                        type="button"
                        onClick={() => onRemoveItem(item.skuCode)}
                        className="text-slate-400 hover:text-red-500 p-0.5 rounded transition cursor-pointer"
                        title="删除"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                          />
                        </svg>
                      </button>
                    </div>

                    <div className="text-[11px] text-slate-500 mt-0.5 bg-slate-100 inline-block px-1.5 py-0.5 rounded">
                      {Object.entries(item.specAttributes || {})
                        .map(([k, v]) => `${k}: ${v}`)
                        .join(' / ') || item.skuTitle}
                    </div>

                    <div className="flex items-center justify-between mt-2">
                      <div className="text-emerald-700 font-extrabold text-sm">¥{item.price.toFixed(2)}</div>

                      {/* 数量加减器 */}
                      <div className="flex items-center border border-slate-200 rounded-lg bg-white overflow-hidden shadow-2xs">
                        <button
                          type="button"
                          onClick={() => onUpdateQuantity(item.skuCode, -1)}
                          disabled={item.quantity <= 1}
                          className="px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-30 disabled:hover:bg-transparent cursor-pointer"
                        >
                          -
                        </button>
                        <span className="px-2.5 py-0.5 text-xs font-semibold text-slate-800 min-w-6 text-center">
                          {item.quantity}
                        </span>
                        <button
                          type="button"
                          onClick={() => onUpdateQuantity(item.skuCode, 1)}
                          disabled={item.quantity >= item.stock}
                          className="px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-30 disabled:hover:bg-transparent cursor-pointer"
                        >
                          +
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 抽屉底部结算栏 Footer */}
        {cart.length > 0 && (
          <div className="p-4 border-t border-slate-200 bg-white space-y-3">
            <div className="flex items-center justify-between text-xs text-slate-600">
              <label className="flex items-center space-x-2 cursor-pointer select-none">
                <Checkbox checked={isAllSelected} onCheckedChange={onToggleSelectAll} />
                <span>全选 ({cart.length})</span>
              </label>

              <div className="text-right">
                <span className="text-xs text-slate-500">已选 {totalCount} 件，合计：</span>
                <span className="text-lg font-black text-emerald-700 ml-1">¥{totalPrice.toFixed(2)}</span>
              </div>
            </div>

            <Button
              type="button"
              onClick={onCheckout}
              disabled={selectedItems.length === 0 || isCheckingOut || !selectedAddress}
              className="w-full py-3 h-auto bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-xl shadow-md transition-all flex items-center justify-center space-x-2"
            >
              {isCheckingOut ? <span>正在提交订单...</span> : <span>立即结算 ({selectedItems.length})</span>}
            </Button>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
};
