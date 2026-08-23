import crypto from 'node:crypto';

export class HmacSigner {
  /**
   * 生成标准 HMAC-SHA256 签名
   * 签名要素: HTTP_METHOD + \n + PATH + \n + TIMESTAMP + \n + NONCE + \n + HASH(BODY)
   */
  public static sign(params: {
    method: string;
    path: string;
    timestamp: number;
    nonce: string;
    body: string;
    secret: string;
  }): string {
    const bodyHash = crypto
      .createHash('sha256')
      .update(params.body || '')
      .digest('hex');
    const signaturePayload = [
      params.method.toUpperCase(),
      params.path,
      params.timestamp.toString(),
      params.nonce,
      bodyHash,
    ].join('\n');

    return crypto.createHmac('sha256', params.secret).update(signaturePayload).digest('hex');
  }

  /**
   * 校验来自第三方的回调签名
   */
  public static verify(params: {
    method: string;
    path: string;
    timestamp: number;
    nonce: string;
    body: string;
    secret: string;
    signature: string;
  }): boolean {
    if (!params.signature || typeof params.signature !== 'string') {
      return false;
    }
    const expected = HmacSigner.sign(params);
    try {
      const bufA = Buffer.from(expected, 'hex');
      const bufB = Buffer.from(params.signature, 'hex');
      if (bufA.length !== bufB.length) {
        return false;
      }
      return crypto.timingSafeEqual(bufA, bufB);
    } catch {
      return false;
    }
  }
}
