---
description: Tools registry, PII scrubbing, caching, and Puppeteer screenshot guidelines
paths: ["packages/tools/**/*"]
---

# Tools Registry Rules

This workspace defines the tools callable by the Agent's executor node.

## Architecture

- **Standardized Schema:** Registered using a Zod validator schema inside `packages/tools/src/registry.ts`.
- **PII Scrubbing Middleware:** Sensitive parameters (phones, ID cards, emails, bank cards, auth tokens) are masked via `scrubPii()` in `packages/tools/src/scrubber.ts` before logging or persisting.
- **E-Commerce Tools & Multi-Level Cache:** `getOrderStatus` and `processRefund` operate directly against DB interfaces. `getOrderStatus` includes a **Second Shield (Tool-Level Cache)** with dual-mode fallback (1-min TTL: Redis first, In-Memory `Map` fallback).
- **Physical Screenshots:** `takeScreenshot` runs Puppeteer headless Chrome and saves physical PNG files to `apps/web/public/screenshots/`.

## Guidelines

- Always register new tools in the central registry using `registerTool()`.
- Respect **cache coherence**: Any write/mutation tool (e.g., `processRefund`) must immediately invalidate cached entries for that `orderId`.
- Always apply `scrubPii()` to tool execution inputs/outputs in logs and telemetry payloads.
- Avoid passing large base64 images through Temporal/SSE memory. Save to disk and return relative URLs instead.
- Puppeteer logic must include proper resource cleanup (close browser in `finally` blocks) and cross-platform executable path detection.
