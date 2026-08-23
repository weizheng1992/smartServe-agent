import type { NextRequest } from 'next/server';
import { HmacSigner } from 'tools';
import { MerchantDomainService } from './merchantDomainService';

export async function verifySpiRequest(
  req: NextRequest,
  bodyStr = '',
  options: { requireSignature?: boolean } = { requireSignature: true },
): Promise<{ isValid: boolean; error?: string }> {
  const signature = req.headers.get('x-signature');
  const timestamp = req.headers.get('x-timestamp');
  const nonce = req.headers.get('x-nonce');

  if (!signature) {
    if (options.requireSignature) {
      return {
        isValid: false,
        error: 'Missing x-signature header for protected SPI endpoint',
      };
    }
    return { isValid: true };
  }

  if (!timestamp || !nonce) {
    return {
      isValid: false,
      error: 'Missing x-timestamp or x-nonce headers for signed request',
    };
  }

  const reqTime = Number.parseInt(timestamp, 10);
  const now = Date.now();
  // 5 分钟时效窗口防重放攻击
  if (Math.abs(now - reqTime) > 300000) {
    return {
      isValid: false,
      error: 'Request timestamp expired (> 5 minutes window)',
    };
  }

  const urlObj = new URL(req.url);
  const isValid = HmacSigner.verify({
    method: req.method,
    path: urlObj.pathname,
    timestamp: reqTime,
    nonce,
    body: bodyStr,
    secret: MerchantDomainService.API_SECRET,
    signature,
  });

  if (!isValid) {
    return { isValid: false, error: 'Invalid HMAC-SHA256 signature' };
  }

  return { isValid: true };
}
