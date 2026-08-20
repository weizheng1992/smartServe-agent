---
description: Database schema, multi-tenant isolation, and ORM client guidelines
paths: ["packages/db/**/*", "drizzle.config.ts"]
---

# Database & ORM Rules

This workspace coordinates PostgreSQL structures, multi-tenant data safety, and Drizzle ORM client interactions.

## Architecture

- **ORM:** Managed via Drizzle ORM. Schemas are defined in `packages/db/src/schema.ts`.
- **Pure PostgreSQL (Single Source of Truth):** Direct connection to real PostgreSQL database pool via `packages/db/src/client.ts`.
- **Tenant Isolation:** All business entities (`orders`, `ragDocuments`, `messages`, `telemetrySessions`) include tenant/business partitions (`business_id`).

## Guidelines

- Always use standard PostgreSQL connection pool (`pg.Pool`) and Drizzle ORM queries.
- When changing table structures in `schema.ts`, update matching types in `packages/types`.
- Always include explicit `business_id` / tenant equality predicates in queries to prevent cross-tenant data leaks.
- Use drizzle-kit commands for migrations: `bun drizzle-kit generate`, `bun drizzle-kit push`.
