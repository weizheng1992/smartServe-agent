import { describe, expect, it } from 'bun:test';
import { decryptSecret, deriveTenantKey, encryptSecret, redactSensitiveObject } from '../src/crypto/secrets';

describe('Phase 4: Tenant Secrets Encryption & Redaction (TDD)', () => {
  const masterKey = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'; // 32-byte hex
  const tenantId = 'nike_global';
  const plaintext = 'sk-live-secret-token-for-nike-api-987654';

  it('should derive deterministic 32-byte key for a given tenant using HKDF', () => {
    const key1 = deriveTenantKey(masterKey, tenantId);
    const key2 = deriveTenantKey(masterKey, tenantId);
    const keyOther = deriveTenantKey(masterKey, 'adidas_global');

    expect(key1).toHaveLength(32);
    expect(key1).toEqual(key2);
    expect(key1).not.toEqual(keyOther);
  });

  it('should encrypt plaintext into iv:authTag:ciphertext format', () => {
    const encrypted = encryptSecret(plaintext, masterKey, tenantId);
    expect(encrypted).toBeDefined();

    const parts = encrypted.split(':');
    expect(parts).toHaveLength(3);
    expect(parts[0]).toHaveLength(24); // 12 bytes = 24 hex
    expect(parts[1]).toHaveLength(32); // 16 bytes = 32 hex
    expect(parts[2].length).toBeGreaterThan(0);
  });

  it('should successfully decrypt encrypted secret with the matching tenant key', () => {
    const encrypted = encryptSecret(plaintext, masterKey, tenantId);
    const decrypted = decryptSecret(encrypted, masterKey, tenantId);

    expect(decrypted).toBe(plaintext);
  });

  it('should throw error if attempting to decrypt with incorrect tenant key or tampered tag', () => {
    const encrypted = encryptSecret(plaintext, masterKey, tenantId);

    // Wrong tenant
    expect(() => {
      decryptSecret(encrypted, masterKey, 'different_tenant');
    }).toThrow();

    // Tampered payload
    const tampered = encrypted.substring(0, encrypted.length - 4) + '0000';
    expect(() => {
      decryptSecret(tampered, masterKey, tenantId);
    }).toThrow();
  });

  it('should recursively redact sensitive headers and API tokens from payload objects', () => {
    const rawPayload = {
      authorization: 'Bearer secret-token-xyz',
      headers: {
        'x-api-key': 'sensitive-api-key-value',
        'content-type': 'application/json',
      },
      apiKey: 'secret-key-123',
      nested: {
        clientSecret: 'top-secret-password',
        publicName: 'Order Inquiry',
      },
    };

    const redacted = redactSensitiveObject(rawPayload);

    expect(redacted.authorization).toBe('[REDACTED]');
    expect(redacted.headers['x-api-key']).toBe('[REDACTED]');
    expect(redacted.headers['content-type']).toBe('application/json');
    expect(redacted.apiKey).toBe('[REDACTED]');
    expect(redacted.nested.clientSecret).toBe('[REDACTED]');
    expect(redacted.nested.publicName).toBe('Order Inquiry');
  });
});
