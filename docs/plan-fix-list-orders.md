# Implementation Plan - Fixing listUserOrders Tool in Local Emulator

## Context & Alignment Info
* **User's Verbatim Instruction**: "我选择 adidas 然后问我有多少订单，回复我没有"
* **Affected API / Core Systems**: `listUserOrders` tool execution in local database emulator (`FakePool` query method in `packages/db/src/client.ts`).
* **Importers & Callers**: `listUserOrders` in `packages/tools/src/ecommerce.tools.ts` calls `db.execute()`.
* **Data Schemas**: `orders` schema (defined in `packages/db/src/schema.ts`) contains `orderId` (mapped to `order_id` in PG), `userId` (mapped to `user_id`), `businessId` (mapped to `business_id`), etc.

## 1. Problem Statement
When a user switches to Adidas in the frontend and asks "how many orders do I have?", the AI replies that they have none.

After deep systematic tracing, we found the root cause:
1. **Double Quotes SQL Regex Defect**: In `FakePool.query`, the regex used to detect user queries by `user_id` was:
   `s.match(/user_id\s*=\s*['"]([^'"]+)['"]/i) || s.match(/user_id\s*=\s*\$1/i)`
   However, the `listUserOrders` tool executes a query using Drizzle-aligned SQL with double quotes:
   `SELECT ... FROM orders WHERE "user_id" = $1 AND "business_id" = $2`
   Since there is a double quote `"` immediately after `user_id`, the `\s*` whitespace check failed to match it, causing `userMatch` to be `false`!
2. **Missing Business Tenant Separation in Emulator**: In emulator mode, `FakePool` did not inspect or filter by the second parameter (`business_id = $2`), meaning it did not respect the multi-tenant SaaS boundaries.
3. **Key Casing Mismatch in Emulator**: The database emulator stores orders with snake_case keys (`order_id`, `tracking_number`, `estimated_delivery`, `total_amount`), but the query and tools expect camelCase aliases (`orderId`, `trackingNumber`, etc.).

## 2. Proposed Changes

### Modify `packages/db/src/client.ts` (`FakePool.query` Method)
We will rewrite the `FROM ORDERS` section to:
1. Make `userMatch` regex resilient to optional single/double quotes around `user_id`, e.g., `/["']?user_id["']?\s*=\s*\$1/i`.
2. Extract the `business_id` parameter and perform filtering if `business_id = $2` is found in the SQL query.
3. Automatically map returned rows with BOTH camelCase and snake_case properties to prevent any downstream casing/mapping issues.

```typescript
    if (s.toUpperCase().includes('FROM ORDERS') || s.toUpperCase().includes('FROM "ORDERS"')) {
      // Check if querying by user_id
      const userMatch = s.match(/user_id\s*=\s*['"]([^'"]+)['"]/i) || s.match(/["']?user_id["']?\s*=\s*\$1/i);
      if (userMatch) {
        const userId = params && typeof params[0] === 'string' ? params[0] : 'u_default_id';
        let rows = Array.from(memoryDb.orders.values()).filter((o) => o.user_id === userId);

        // Also check if querying with business_id constraint (multi-tenant filtering in emulator!)
        const businessMatch = s.match(/["']?business_id["']?\s*=\s*\$2/i);
        if (businessMatch && params && typeof params[1] === 'string') {
          const businessId = params[1];
          rows = rows.filter((o) => o.business_id === businessId);
        }

        // Map columns to include both camelCase and snake_case fields for bulletproof compatibility
        const mappedRows = rows.map((o) => ({
          ...o,
          orderId: o.order_id,
          trackingNumber: o.tracking_number,
          estimatedDelivery: o.estimated_delivery,
          totalAmount: o.total_amount,
          userId: o.user_id,
          businessId: o.business_id,
        }));

        return { rows: mappedRows } as DBQueryResult<unknown>;
      }
```

## 3. Success Criteria
1. The modified regex correctly parses SQL queries like `WHERE "user_id" = $1 AND "business_id" = $2`.
2. Running the tool locally or via CLI returns the correct orders matching the current active tenant (Adidas/Nike/Ecommerce).
3. The linter compiles with 0 errors.
