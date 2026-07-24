---
description: Database schema and ORM client guidelines
paths: ["packages/db/**/*", "drizzle.config.ts"]
---
# Database & ORM Rules

This workspace coordinates PostgreSQL structures and handles mock database interactions.

## Architecture
- **ORM:** Managed via Drizzle ORM. Schemas are defined in `packages/db/src/schema.ts`.
- **High-Fidelity Memory DB Fallback:** If a real Postgres DB is offline, `packages/db/src/client.ts` starts a simulated memory database (`FakePool`) that intercepts Drizzle actions and implements standard mutations.

## Guidelines
- Always maintain compatibility between real Postgres schema actions and the memory-database emulator (`FakePool` inside `packages/db/src/client.ts`).
- When changing table structures in `schema.ts`, make sure to update the matching types and emulation actions inside the `FakePool` emulator.
- Use drizzle-kit commands for migrations: `bun drizzle-kit generate`, `bun drizzle-kit push`.
