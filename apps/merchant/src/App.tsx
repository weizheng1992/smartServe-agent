import { BrowserRouter, Route, Routes } from 'react-router';
import { FloatingChatWidget } from './components/chat/FloatingChatWidget';
import { UserProvider } from './context/UserContext';
import AddressesPage from './pages/AddressesPage';
import CartPage from './pages/CartPage';
import MerchantAdminPage from './pages/MerchantAdminPage';
import OrderDetailPage from './pages/OrderDetailPage';
import OrdersPage from './pages/OrdersPage';
import ProductDetailPage from './pages/ProductDetailPage';
import StorefrontPage from './pages/StorefrontPage';

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
        <FloatingChatWidget />
      </BrowserRouter>
    </UserProvider>
  );
}
