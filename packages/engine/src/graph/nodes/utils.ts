const ORDER_ID_REGEX = /\bORD-[A-Za-z0-9]+\b/i;

export interface MessageLike {
  role?: string;
  content?: string | null;
}

/**
 * Extract Order ID (e.g. "ORD-98712") from primary text, secondary text, or short memory context.
 */
export function extractOrderId(
  primaryText?: string | null,
  secondaryText?: string | null,
  shortMemory?: MessageLike[] | null,
): string | null {
  if (primaryText) {
    const match = primaryText.match(ORDER_ID_REGEX);
    if (match) return match[0].toUpperCase();
  }

  if (secondaryText) {
    const match = secondaryText.match(ORDER_ID_REGEX);
    if (match) return match[0].toUpperCase();
  }

  if (shortMemory && shortMemory.length > 0) {
    for (let i = shortMemory.length - 1; i >= 0; i--) {
      const msg = shortMemory[i];
      if (msg && msg.role === "user" && msg.content) {
        const match = msg.content.match(ORDER_ID_REGEX);
        if (match) return match[0].toUpperCase();
      }
    }
  }

  return null;
}
