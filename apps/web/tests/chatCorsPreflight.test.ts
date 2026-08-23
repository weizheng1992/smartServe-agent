import { describe, expect, it } from 'bun:test';
import { NextRequest } from 'next/server';
import { OPTIONS, POST } from '../app/api/chat/route';

describe('🌐 API Gateway CORS & Cross-Origin Preflight Suite', () => {
  const TEST_ORIGIN = 'http://localhost:3005';

  it('1. OPTIONS preflight request should return 204/200 with CORS headers', async () => {
    const req = new NextRequest('http://localhost:3000/api/chat', {
      method: 'OPTIONS',
      headers: {
        Origin: TEST_ORIGIN,
        'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'Content-Type',
      },
    });

    const res = await OPTIONS(req);
    expect(res.status).toBe(204);
    expect(res.headers.get('Access-Control-Allow-Origin')).toBe('*');
    expect(res.headers.get('Access-Control-Allow-Methods')).toContain('POST');
    expect(res.headers.get('Access-Control-Allow-Headers')).toContain('Content-Type');
  });

  it('2. POST /api/chat cross-origin request should return Access-Control-Allow-Origin header', async () => {
    const req = new NextRequest('http://localhost:3000/api/chat', {
      method: 'POST',
      headers: {
        Origin: TEST_ORIGIN,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message: '你好',
        businessId: 'aurora',
        userId: 'CUST-8801',
      }),
    });

    const res = await POST(req);
    expect(res.status).toBe(200);
    expect(res.headers.get('Access-Control-Allow-Origin')).toBe('*');
  });
});
