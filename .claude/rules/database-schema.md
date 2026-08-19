---
description: Database schema, multi-tenant isolation, and ORM client guidelines
paths: ["packages/db/**/*", "drizzle.config.ts"]
---

# Database & ORM Rules

This workspace coordinates PostgreSQL structures, multi-tenant data safety, and handles mock database interactions.

## Architecture

- **ORM:** Managed via Drizzle ORM. Schemas are defined in `packages/db/src/schema.ts`.
- **High-Fidelity Memory DB Fallback:** If a real Postgres DB is offline, `packages/db/src/client.ts` starts a simulated memory database (`FakePool`) that intercepts Drizzle actions and implements standard mutations.
- **Tenant Isolation:** All business entities (`orders`, `ragDocuments`, `messages`, `telemetrySessions`) include `tenantId` partitions.

## Guidelines

- Always maintain compatibility between real Postgres schema actions and the memory-database emulator (`FakePool` inside `packages/db/src/client.ts`).
- When changing table structures in `schema.ts`, update matching types and emulation actions inside the `FakePool` emulator.
- Always include explicit `tenantId` equality predicates in queries to prevent cross-tenant data leaks.
- Use drizzle-kit commands for migrations: `bun drizzle-kit generate`, `bun drizzle-kit push`.
