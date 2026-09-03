import React, { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { useNavigate, useParams } from 'react-router';
import type { ThirdPartyProduct, ThirdPartySku } from 'types';
import { Badge, Button } from 'ui';
import { StorefrontHeader } from '../components/navbar/StorefrontHeader';

export default function ProductDetailPage() {
  const params = useParams();
  const navigate = useNavigate();
  const productId = params?.id as string;

  const [product, setProduct] = useState<ThirdPartyProduct | null>(null);
  const [selectedSku, setSelectedSku] = useState<ThirdPartySku | null>(null);
  const [selectedAttrs, setSelectedAttrs] = useState<Record<string, string>>({});
  const [buyQuantity, setBuyQuantity] = useState(1);
  const [activeImage, setActiveImage] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isAddingToCart, setIsAddingToCart] = useState(false);
  const [cartSuccessMessage, setCartSuccessMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!productId) return;
    const fetchProduct = async () => {
      setLoading(true);
      try {
        const res = await fetch(`/api/store/products/${productId}`);
        const data = await res.json();
        if (data.success && data.product) {
          const p: ThirdPartyProduct = data.product;
          setProduct(p);
          setActiveImage(p.imageUrl || '');
          if (p.skus && p.skus.length > 0) {
            setSelectedSku(p.skus[0]);
            setSelectedAttrs(p.skus[0].specAttributes || {});
          }
        } else {
          setError(data.error || '商品不存在');
        }
      } catch {
        setError('获取商品详情失败');
      } finally {
        setLoading(false);
      }
    };
    fetchProduct();
  }, [productId]);

  const handleSelectAttr = (dimName: string, val: string) => {
    if (!product) return;
    const nextAttrs = { ...selectedAttrs, [dimName]: val };
    setSelectedAttrs(nextAttrs);

    const matchedSku = product.skus?.find((s) => {
      const attrs = s.specAttributes || {};
      return Object.entries(nextAttrs).every(([k, v]) => attrs[k] === v);
    });

    if (matchedSku) {
      setSelectedSku(matchedSku);
      if (matchedSku.imageUrl) {
        setActiveImage(matchedSku.imageUrl);
      }
    }
  };

  const handleAddToCart = () => {
    if (!product || !selectedSku) return;
    setIsAddingToCart(true);

    try {
      const existingCart = JSON.parse(localStorage.getItem('aurora_store_cart') || '[]');
      const idx = existingCart.findIndex((it: any) => it.sku.skuCode === selectedSku.skuCode);
      if (idx >= 0) {
        existingCart[idx].quantity += buyQuantity;
      } else {
        existingCart.push({
          product,
          sku: selectedSku,
          quantity: buyQuantity,
          selected: true,
        });
      }
      localStorage.setItem('aurora_store_cart', JSON.stringify(existingCart));

      setCartSuccessMessage(`已成功加入购物车！规格：${selectedSku.skuTitle}`);
      setTimeout(() => setCartSuccessMessage(null), 3000);
    } finally {
      setIsAddingToCart(false);
    }
  };

  const handleInstantBuy = () => {
    if (!product || !selectedSku) return;
    handleAddToCart();
    navigate('/cart');
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col">
        <StorefrontHeader />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-slate-500 text-sm flex items-center space-x-2">
            <span className="w-3 h-3 rounded-full bg-emerald-500 animate-ping" />
            <span>正在加载商品数据...</span>
          </div>
        </div>
      </div>
    );
  }

  if (error || !product) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col">
        <StorefrontHeader />
        <div className="max-w-4xl mx-auto my-12 p-8 bg-white rounded-2xl shadow-sm border border-slate-200 text-center">
          <div className="text-4xl mb-3">⚠️</div>
          <h2 className="text-lg font-bold text-slate-800">未能找到该商品</h2>
          <p className="text-xs text-slate-500 mt-1">{error || '商品可能已下架或链接错误'}</p>
          <div className="mt-6">
            <Link
              to="/"
              className="px-4 py-2 bg-emerald-600 text-white rounded-lg text-xs font-semibold hover:bg-emerald-500 transition"
            >
              返回商城首页
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const currentPrice = selectedSku ? Number(selectedSku.price) : Number(product.price);
  const currentStock = selectedSku ? selectedSku.stock : product.stock;

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      <StorefrontHeader />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex-1 w-full">
        {/* 顶部面包屑 */}
        <div className="flex items-center space-x-2 text-xs text-slate-500 mb-6">
          <Link to="/" className="hover:text-emerald-700">
            首页
          </Link>
          <span>/</span>
          <span className="text-slate-700">{product.category}</span>
          <span>/</span>
          <span className="font-medium text-slate-900 truncate max-w-xs">{product.title}</span>
        </div>

        {cartSuccessMessage && (
          <div className="mb-6 p-4 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl text-xs font-semibold flex items-center justify-between animate-in fade-in">
            <div className="flex items-center space-x-2">
              <span>✅</span>
              <span>{cartSuccessMessage}</span>
            </div>
            <Link to="/cart" className="underline hover:text-emerald-950 font-bold">
              去购物车结算 →
            </Link>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 bg-white p-6 sm:p-8 rounded-2xl border border-slate-200 shadow-xs">
          {/* 左侧商品图展示 */}
          <div className="lg:col-span-5 space-y-4">
            <div className="aspect-square bg-slate-100 rounded-xl overflow-hidden border border-slate-200">
              <img src={activeImage || product.imageUrl} alt={product.title} className="w-full h-full object-cover" />
            </div>
            {/* 缩略图轮播列表 */}
            {product.detailImages && product.detailImages.length > 0 && (
              <div className="flex gap-2 overflow-x-auto pb-1">
                <button
                  type="button"
                  onClick={() => setActiveImage(product.imageUrl || '')}
                  className={`w-16 h-16 rounded-lg overflow-hidden border-2 shrink-0 transition ${
                    activeImage === product.imageUrl ? 'border-emerald-600' : 'border-slate-200'
                  }`}
                >
                  <img src={product.imageUrl} alt="main" className="w-full h-full object-cover" />
                </button>
                {product.detailImages.map((imgUrl, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => setActiveImage(imgUrl)}
                    className={`w-16 h-16 rounded-lg overflow-hidden border-2 shrink-0 transition ${
                      activeImage === imgUrl ? 'border-emerald-600' : 'border-slate-200'
                    }`}
                  >
                    <img src={imgUrl} alt="banner" className="w-full h-full object-cover" />
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* 右侧商品规格与购买区域 */}
          <div className="lg:col-span-7 flex flex-col justify-between space-y-6">
            <div className="space-y-4">
              <div className="flex items-center space-x-2">
                <Badge variant="secondary" className="bg-emerald-50 text-emerald-800 border-emerald-200 text-xs">
                  {product.brand}
                </Badge>
                <Badge variant="outline" className="text-xs">
                  {product.category}
                </Badge>
              </div>

              <div>
                <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight">{product.title}</h1>
                {product.subtitle && <p className="text-xs text-slate-500 mt-1">{product.subtitle}</p>}
              </div>

              {/* 价格区块 */}
              <div className="bg-slate-50 p-4 rounded-xl border border-slate-200 flex items-baseline space-x-3">
                <span className="text-emerald-700 font-extrabold text-3xl">¥{currentPrice.toFixed(2)}</span>
                {product.originalPrice && (
                  <span className="text-xs text-slate-400 line-through">
                    ¥{Number(product.originalPrice).toFixed(2)}
                  </span>
                )}
                <span className="text-xs text-slate-500 ml-auto">
                  库存: <strong className="text-emerald-700">{currentStock}</strong> 件
                </span>
              </div>

              {/* 多维规格选择 */}
              {product.specDimensions?.map((dim) => (
                <div key={dim.name} className="space-y-2">
                  <label className="block text-xs font-bold text-slate-700">{dim.name}</label>
                  <div className="flex flex-wrap gap-2">
                    {dim.values.map((val) => {
                      const isSelected = selectedAttrs[dim.name] === val;
                      return (
                        <button
                          key={val}
                          type="button"
                          onClick={() => handleSelectAttr(dim.name, val)}
                          className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition cursor-pointer ${
                            isSelected
                              ? 'bg-emerald-600 text-white border-emerald-600 shadow-xs'
                              : 'bg-white text-slate-700 border-slate-200 hover:border-slate-400'
                          }`}
                        >
                          {val}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}

              {/* 数量选择 */}
              <div className="flex items-center space-x-4 pt-2">
                <span className="text-xs font-bold text-slate-700">购买数量</span>
                <div className="flex items-center border border-slate-200 rounded-lg overflow-hidden bg-white shadow-2xs">
                  <button
                    type="button"
                    onClick={() => setBuyQuantity((q) => Math.max(1, q - 1))}
                    disabled={buyQuantity <= 1}
                    className="px-3 py-1 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-30"
                  >
                    -
                  </button>
                  <span className="px-4 py-1 text-xs font-bold text-slate-800 min-w-8 text-center">{buyQuantity}</span>
                  <button
                    type="button"
                    onClick={() => setBuyQuantity((q) => Math.min(currentStock, q + 1))}
                    disabled={buyQuantity >= currentStock}
                    className="px-3 py-1 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-30"
                  >
                    +
                  </button>
                </div>
              </div>
            </div>

            {/* 购买与加购操作按钮 */}
            <div className="pt-6 border-t border-slate-100 flex items-center gap-3">
              <Button
                type="button"
                variant="outline"
                onClick={handleAddToCart}
                disabled={currentStock <= 0 || isAddingToCart}
                className="flex-1 py-5 text-xs font-bold border-amber-300 bg-amber-50 text-amber-900 hover:bg-amber-100"
              >
                🛒 加入购物车
              </Button>
              <Button
                type="button"
                onClick={handleInstantBuy}
                disabled={currentStock <= 0}
                className="flex-1 py-5 text-xs font-bold bg-emerald-600 text-white hover:bg-emerald-500 shadow-xs"
              >
                ⚡ 立即购买
              </Button>
            </div>
          </div>
        </div>

        {/* 材质与技术参数详情 */}
        <div className="mt-8 bg-white p-6 sm:p-8 rounded-2xl border border-slate-200 shadow-xs space-y-4">
          <h2 className="text-base font-bold text-slate-900 border-b border-slate-100 pb-3">商品详情与技术参数</h2>
          <p className="text-xs text-slate-600 leading-relaxed">{product.description}</p>
          {product.specs && Object.keys(product.specs).length > 0 && (
            <div className="border border-slate-200 rounded-xl overflow-hidden mt-4">
              <table className="w-full text-left text-xs">
                <tbody className="divide-y divide-slate-100">
                  {Object.entries(product.specs).map(([key, value]) => (
                    <tr key={key}>
                      <td className="p-3 bg-slate-50 text-slate-500 font-semibold w-36">{key}</td>
                      <td className="p-3 text-slate-800">{value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
