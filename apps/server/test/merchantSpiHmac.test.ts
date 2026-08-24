import { describe, expect, it } from 'bun:test';
import { HmacSigner } from 'tools';
import { MerchantSpiService } from '../src/modules/spi/merchant-spi.controller';

describe('🛡️ Merchant SPI HMAC Authentication & Replay Protection Suite', () => {
  const service = new MerchantSpiService();
  const secret = 'secret_nike';
  const tenantId = 'nike';

  it('should successfully authenticate request with valid HMAC signature', async () => {
    const timestamp = Date.now();
    const nonce = 'nonce_12345';
    const method = 'POST';
    const path = '/api/v1/spi/approvals/app_1/resolve';
    const bodyStr = JSON.stringify({ action: 'approve' });

    const signature = HmacSigner.sign({
      method,
      path,
      timestamp,
      nonce,
      body: bodyStr,
      secret,
    });

    const isAuthed = await service.authenticateMerchant({
      tenantId,
      signature,
      timestamp,
      nonce,
      bodyStr,
      method,
      path,
    });

    expect(isAuthed).toBe(true);
  });

  it('should reject HMAC request with tampered body payload', async () => {
    const timestamp = Date.now();
    const nonce = 'nonce_12345';
    const method = 'POST';
    const path = '/api/v1/spi/approvals/app_1/resolve';
    const originalBody = JSON.stringify({ action: 'approve' });
    const tamperedBody = JSON.stringify({ action: 'reject' });

    const signature = HmacSigner.sign({
      method,
      path,
      timestamp,
      nonce,
      body: originalBody,
      secret,
    });

    const isAuthed = await service.authenticateMerchant({
      tenantId,
      signature,
      timestamp,
      nonce,
      bodyStr: tamperedBody,
      method,
      path,
    });

    expect(isAuthed).toBe(false);
  });

  it('should reject HMAC request when timestamp exceeds 300 seconds window (replay attack prevention)', async () => {
    const staleTimestamp = Date.now() - 400_000; // 400 seconds ago (> 300s)
    const nonce = 'nonce_stale_999';
    const method = 'POST';
    const path = '/api/v1/spi/approvals/app_1/resolve';
    const bodyStr = JSON.stringify({ action: 'approve' });

    const signature = HmacSigner.sign({
      method,
      path,
      timestamp: staleTimestamp,
      nonce,
      body: bodyStr,
      secret,
    });

    const isAuthed = await service.authenticateMerchant({
      tenantId,
      signature,
      timestamp: staleTimestamp,
      nonce,
      bodyStr,
      method,
      path,
    });

    expect(isAuthed).toBe(false);
  });

  it('should accept valid tenant API Key', async () => {
    const isAuthed = await service.authenticateMerchant({
      tenantId: 'adidas',
      apiKey: 'key_adidas',
    });
    expect(isAuthed).toBe(true);
  });

  it('should reject invalid tenant or empty tenant identifier', async () => {
    const isAuthed = await service.authenticateMerchant({
      tenantId: '',
      apiKey: 'any_key',
    });
    expect(isAuthed).toBe(false);
  });
});
