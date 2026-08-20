/**
 * PII (Personally Identifiable Information) Data Scrubber
 * Recursively masks sensitive fields (Phone, ID card, Email, Bank Card) in tool inputs/outputs and logs.
 */

const PHONE_REGEX = /(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)/g;
const ID_CARD_REGEX = /(?<!\d)([1-9]\d{5})\d{8}(\d{3}[\dX])(?!\d)/gi;
const EMAIL_REGEX = /\b([a-zA-Z0-9._%+-]{1,2})[a-zA-Z0-9._%+-]*@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b/g;
const BANK_CARD_REGEX = /(?<!\d)(\d{4})\d{8,11}(\d{4})(?!\d)/g;

export function scrubPiiString(text: string): string {
  if (!text) return text;
  return text
    .replace(PHONE_REGEX, '$1****$2')
    .replace(ID_CARD_REGEX, '$1********$2')
    .replace(EMAIL_REGEX, '$1***@$2')
    .replace(BANK_CARD_REGEX, '$1********$2');
}

export function scrubPii<T>(val: T): T {
  if (val === null || val === undefined) {
    return val;
  }

  if (typeof val === 'string') {
    return scrubPiiString(val) as unknown as T;
  }

  if (Array.isArray(val)) {
    return val.map((item) => scrubPii(item)) as unknown as T;
  }

  if (typeof val === 'object') {
    const scrubbedObj: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(val)) {
      // Sensitive field names can be masked or scrubbed recursively
      if (typeof value === 'string' && /password|secret|token|auth/i.test(key)) {
        scrubbedObj[key] = '******';
      } else {
        scrubbedObj[key] = scrubPii(value);
      }
    }
    return scrubbedObj as unknown as T;
  }

  return val;
}
