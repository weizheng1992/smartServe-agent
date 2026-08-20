import crypto from "node:crypto";

const INFO_CONTEXT = "tenant-api-secrets-v1";

/**
 * 基于主密钥与租户标识 (Salt)，利用 RFC 5869 HKDF 派生租户专属的 32 字节 AES 密钥
 */
export function deriveTenantKey(masterKey: string, tenantId: string): Buffer {
  const ikm = Buffer.from(masterKey, masterKey.length === 64 ? "hex" : "utf8");
  const salt = Buffer.from(tenantId, "utf8");
  const info = Buffer.from(INFO_CONTEXT, "utf8");

  return Buffer.from(crypto.hkdfSync("sha256", ikm, salt, info, 32));
}

/**
 * 使用 AES-256-GCM 加密商户敏感凭证，输出 iv:authTag:ciphertext 格式
 */
export function encryptSecret(
  plaintext: string,
  masterKey: string = process.env.ENCRYPTION_MASTER_KEY ||
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  tenantId: string,
): string {
  const key = deriveTenantKey(masterKey, tenantId);
  const iv = crypto.randomBytes(12); // 96-bit IV for AES-GCM

  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
  const encrypted = Buffer.concat([
    cipher.update(plaintext, "utf8"),
    cipher.final(),
  ]);
  const authTag = cipher.getAuthTag();

  return `${iv.toString("hex")}:${authTag.toString("hex")}:${encrypted.toString("hex")}`;
}

/**
 * 解密 AES-256-GCM 格式的商户凭据，并验证 AuthTag 完整性
 */
export function decryptSecret(
  ciphertextPayload: string,
  masterKey: string = process.env.ENCRYPTION_MASTER_KEY ||
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  tenantId: string,
): string {
  const parts = ciphertextPayload.split(":");
  if (parts.length !== 3) {
    throw new Error(
      "Invalid encrypted payload format. Expected iv:authTag:ciphertext",
    );
  }

  const [ivHex, tagHex, cipherHex] = parts;
  const key = deriveTenantKey(masterKey, tenantId);
  const iv = Buffer.from(ivHex, "hex");
  const authTag = Buffer.from(tagHex, "hex");
  const ciphertext = Buffer.from(cipherHex, "hex");

  const decipher = crypto.createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAuthTag(authTag);

  const decrypted = Buffer.concat([
    decipher.update(ciphertext),
    decipher.final(),
  ]);

  return decrypted.toString("utf8");
}

/**
 * 递归脱敏包含敏感词（如 Authorization, ApiKey, Secret, Password）的 Payload 数据
 */
export function redactSensitiveObject<T>(target: T): T {
  if (target === null || target === undefined) {
    return target;
  }

  if (Array.isArray(target)) {
    return target.map((item) => redactSensitiveObject(item)) as unknown as T;
  }

  if (typeof target === "object") {
    const result: Record<string, unknown> = {};
    const SENSITIVE_PATTERN =
      /^(authorization|x-api-key|apiKey|api_key|clientSecret|secret|password|token|bearer)$/i;

    for (const [key, value] of Object.entries(target)) {
      if (SENSITIVE_PATTERN.test(key) && typeof value === "string") {
        result[key] = "[REDACTED]";
      } else {
        result[key] = redactSensitiveObject(value);
      }
    }
    return result as T;
  }

  return target;
}
