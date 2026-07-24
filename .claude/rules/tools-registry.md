---
description: Tools registry and Puppeteer screenshot guidelines
paths: ["packages/tools/**/*"]
---
# Tools Registry Rules

This workspace defines the tools callable by the Agent's executor node.

## Architecture
- **Standardized Schema:** Registered using a Zod validator schema inside `packages/tools/src/registry.ts`.
- **E-Commerce Tools:** `getOrderStatus` and `processRefund` operate directly against db interfaces. `getOrderStatus` includes a **Second Shield (Tool-Level Cache)** with a safe dual-mode setup (1-minute TTL): attempts Redis first, and automatically falls back to an In-Memory `Map` if Redis is offline. This prevents repeated physical DB queries for identical order IDs.
- **Physical screenshots:** `takeScreenshot` runs a Puppeteer headless Chrome session and saves screenshots directly as physical PNG files in the Next.js `public/screenshots/` folder.

## Guidelines
- Always register new tools in the central registry using `registerTool()`.
- Respect **cache coherence**: If a write/mutation tool modifies order data (e.g., `processRefund`), it must invalidate any cached entries for that `orderId` immediately.
- Avoid passing huge base64 images as return values to protect Temporal/SSE memory. Save them as local files on disk and return relative URLs instead.
- Puppeteer logic must include proper resource cleanup (browser closing in `finally` or catch blocks) and platform-specific executable path detection.
