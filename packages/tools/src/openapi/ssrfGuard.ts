import dns from "node:dns/promises";

const PRIVATE_IP_REGEX = [
  /^127\./, // 127.0.0.0/8 (Loopback)
  /^10\./, // 10.0.0.0/8 (Private)
  /^172\.(1[6-9]|2[0-9]|3[0-1])\./, // 172.16.0.0/12 (Private)
  /^192\.168\./, // 192.168.0.0/16 (Private)
  /^169\.254\./, // 169.254.0.0/16 (Link-Local & Cloud Metadata)
  /^0\.0\.0\.0$/, // All interfaces
  /^::1$/, // IPv6 Loopback
  /^fe80:/i, // IPv6 Link-Local
  /^fc00:/i, // IPv6 Unique Local
];

function isPrivateIp(ip: string): boolean {
  return PRIVATE_IP_REGEX.some((regex) => regex.test(ip));
}

/**
 * 校验目标 URL 是否安全（防御 SSRF 攻击、私有 IP 嗅探及元数据端点穿透）
 */
export async function isSafeUrl(
  urlStr: string,
): Promise<{ safe: boolean; reason?: string }> {
  try {
    const parsed = new URL(urlStr);

    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return { safe: false, reason: `Disallowed protocol: ${parsed.protocol}` };
    }

    const hostname = parsed.hostname.toLowerCase();

    if (hostname === "localhost" || hostname.endsWith(".localhost")) {
      return { safe: false, reason: "Blocking localhost loopback access." };
    }

    // Direct IP check
    if (isPrivateIp(hostname)) {
      return {
        safe: false,
        reason: `Blocking private or link-local IP: ${hostname}`,
      };
    }

    // DNS Resolution check to prevent DNS Rebinding / Intranet probing
    try {
      const lookupResult = await dns.lookup(hostname, { all: true });
      for (const entry of lookupResult) {
        if (isPrivateIp(entry.address)) {
          return {
            safe: false,
            reason: `Resolved IP ${entry.address} for host ${hostname} is private/restricted.`,
          };
        }
      }
    } catch {
      // If DNS lookup fails for standard domains, let fetch handle connectivity errors
    }

    return { safe: true };
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return { safe: false, reason: `Invalid URL: ${errMsg}` };
  }
}
