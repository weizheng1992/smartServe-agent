import { BrowserRouter, Route, Routes, useLocation } from 'react-router';
import { FloatingChatWidget } from './components/chat/FloatingChatWidget';
import { UserProvider } from './context/UserContext';
import AddressesPage from './pages/AddressesPage';
import CartPage from './pages/CartPage';
import MerchantAdminPage from './pages/MerchantAdminPage';
import OrderDetailPage from './pages/OrderDetailPage';
import OrdersPage from './pages/OrdersPage';
import ProductDetailPage from './pages/ProductDetailPage';
import StorefrontPage from './pages/StorefrontPage';

/** 顾客浮动客服窗仅服务商城前台路由;商户运营台(/admin)是员工工作面,
 *  挂顾客组件会遮挡操作按钮且语义错位(admin-readiness 11 审计发现)。 */
function FloatingChatOnStorefrontOnly() {
  const { pathname } = useLocation();
  if (pathname.startsWith('/admin')) return null;
  return <FloatingChatWidget />;
}

export default function App() {
  return (
    <UserProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<StorefrontPage />} />
          <Route path="/products/:id" element={<ProductDetailPage />} />
          <Route path="/cart" element={<CartPage />} />
          <Route path="/orders" element={<OrdersPage />} />
          <Route path="/orders/:id" element={<OrderDetailPage />} />
          <Route path="/addresses" element={<AddressesPage />} />
          <Route path="/admin" element={<MerchantAdminPage />} />
        </Routes>
        <FloatingChatOnStorefrontOnly />
      </BrowserRouter>
    </UserProvider>
  );
}
