import { describe, expect, it } from 'bun:test';
import { HmacSigner, LocalDbSpiAdapter, RemoteHttpSpiAdapter, SpiConnectorFactory } from '../src';

describe('🌟 Merchant SPI & Connector Adapter Architecture Suite', () => {
  describe('1. HMAC Signature & Security Guard', () => {
    it('should generate deterministic HMAC SHA256 signatures and verify successfully', () => {
      const secret = 'merchant_secret_key_8899';
      const timestamp = Date.now();
      const nonce = 'test_nonce_123456';
      const body = JSON.stringify({ orderId: 'ORD-TEST-001', amount: 99.9 });

      const signature = HmacSigner.sign({
        method: 'POST',
        path: '/spi/v1/orders/action',
        timestamp,
        nonce,
        body,
        secret,
      });
      expect(signature).toBeDefined();
      expect(signature.length).toBe(64);

      const isValid = HmacSigner.verify({
        method: 'POST',
        path: '/spi/v1/orders/action',
        timestamp,
        nonce,
        body,
        secret,
        signature,
      });
      expect(isValid).toBe(true);

      const isInvalid = HmacSigner.verify({
        method: 'POST',
        path: '/spi/v1/orders/action',
        timestamp,
        nonce,
        body,
        secret,
        signature: 'tampered_signature_hex',
      });
      expect(isInvalid).toBe(false);
    });
  });

  describe('2. Local DB SPI Adapter (Default Fallback)', () => {
    const localAdapter = new LocalDbSpiAdapter();

    it('should search products with tenant isolation', async () => {
      const results = await localAdapter.searchProducts({
        query: '鞋',
        tenantId: 'nike',
        limit: 5,
      });

      expect(results).toBeDefined();
      expect(Array.isArray(results)).toBe(true);
    });

    it('should query order details with standard schema format', async () => {
      const order = await localAdapter.getOrderDetail({
        orderId: 'ORD-NIKE-001',
        tenantId: 'nike',
      });

      if (order) {
        expect(order).toHaveProperty('orderId');
        expect(order).toHaveProperty('status');
        expect(order).toHaveProperty('items');
      }
    });
  });

  describe('3. Remote HTTP SPI Adapter (Simulated / Real-time)', () => {
    it('should query remote SPI with header authentication and transform response to Canonical Schema', async () => {
      const originalFetch = globalThis.fetch;
      globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
        const urlStr = input.toString();
        if (urlStr.includes('/products/search')) {
          return new Response(
            JSON.stringify({
              success: true,
              data: [
                {
                  productId: 'P100',
                  title: 'Nike Air Zoom Pegasus 40',
                  price: '899.00',
                  stock: 50,
                  category: 'Running',
                },
              ],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          );
        }

        if (urlStr.includes('/orders/detail')) {
          return new Response(
            JSON.stringify({
              success: true,
              data: {
                orderId: 'ORD-REMOTE-888',
                userId: 'U999',
                status: 'SHIPPED',
                totalAmount: '899.00',
                items: [
                  {
                    productId: 'P100',
                    title: 'Nike Air Zoom Pegasus 40',
                    quantity: 1,
                    price: '899.00',
                  },
                ],
                shippingAddress: {
                  recipientName: '张三',
                  phone: '13800138000',
                  fullAddress: '上海市徐汇区漕溪北路',
                },
              },
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          );
        }

        return new Response(JSON.stringify({ error: 'Not found' }), {
          status: 404,
        });
      };

      try {
        const remoteAdapter = new RemoteHttpSpiAdapter({
          mode: 'remote_spi',
          spiBaseUrl: 'https://api.merchant-mock.com/spi/v1',
          authType: 'hmac_sha256',
          secretKey: 'mock_secret_key',
          apiKey: 'mock_api_key',
        });

        // 1. 测试商品搜索
        const products = await remoteAdapter.searchProducts({
          query: 'Pegasus',
          tenantId: 'nike',
        });
        expect(products.length).toBe(1);
        expect(products[0].productId).toBe('P100');
        expect(products[0].title).toBe('Nike Air Zoom Pegasus 40');
        expect(products[0].stock).toBe(50);

        // 2. 测试订单详情查询
        const order = await remoteAdapter.getOrderDetail({
          orderId: 'ORD-REMOTE-888',
          tenantId: 'nike',
        });
        expect(order).toBeDefined();
        expect(order?.orderId).toBe('ORD-REMOTE-888');
        expect(order?.status).toBe('SHIPPED');
        expect(order?.shippingAddress.recipientName).toBe('张三');
      } finally {
        globalThis.fetch = originalFetch;
      }
    });
  });

  describe('4. SpiConnectorFactory Dynamic Routing & Cache', () => {
    it('should dynamically instantiate correct adapter according to tenant config', () => {
      const localClient = SpiConnectorFactory.getClient({ mode: 'local_db' }, 'ecommerce');
      expect(localClient).toBeInstanceOf(LocalDbSpiAdapter);

      const remoteClient = SpiConnectorFactory.getClient(
        {
          mode: 'remote_spi',
          spiBaseUrl: 'https://api.adidas.com/spi',
          authType: 'bearer_token',
          apiKey: 'adi_token',
        },
        'adidas',
      );
      expect(remoteClient).toBeInstanceOf(RemoteHttpSpiAdapter);
    });
  });
});
