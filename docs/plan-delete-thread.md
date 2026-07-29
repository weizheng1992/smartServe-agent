# Implementation Plan - Deleting Conversation Threads in Sidebar

## Context & Alignment Info
* **User's Verbatim Instruction**: "左侧列表 做一个删除对话功能"
* **Affected API / Core Systems**: 
  1. Frontend UI: `apps/web/app/page.tsx`
  2. Next.js API Route: `apps/web/app/api/chat/threads/route.ts`
  3. DB Interface & Implementation: `packages/db/src/client.ts`
* **Dependent Files / Lines Calling/Using**: None, this is a documentation-only implementation plan for this session.
* **No Duplicate Exist**: Confirmed that `docs/plan-delete-thread.md` does not exist in the codebase.
* **Data Fields/Structure**: Contains text describing implementation steps and database tables (`threads`, `messages`, etc.) with their relative relationships.

## 1. Problem Statement
The user requested a feature to delete conversation threads directly from the left sidebar list.
Because of Postgres Foreign Key constraints, a thread cannot be deleted directly if it has dependent records in other tables. We must perform a cascading cleanup of all associated data.

## 2. Proposed Changes

### Step 1: Update DB Interface & Implementation (`packages/db/src/client.ts`)
1. Add `deleteThread: (threadId: string) => Promise<boolean>` to `DBInterface`.
2. Implement `deleteThread` inside the `db` constant:
   - It will cascade-delete records from all tables referencing `thread_id` / `threadId` in Postgres:
     - `messages`
     - `pending_approvals`
     - `session_metrics`
     - `task_memory`
     - `episodic_events`
     - `agent_jobs`
     - `intent_logs`
     - `low_confidence_logs`
   - It will then delete the row from `threads`.
   - It will also perform memory database cleanup for the emulator mode (for maximum robustness and type compatibility).

### Step 2: Implement DELETE Route in Next.js (`apps/web/app/api/chat/threads/route.ts`)
Add a `DELETE` method that extracts `threadId` from search parameters and triggers `db.deleteThread(threadId)`.

### Step 3: Enhance Left Sidebar UI (`apps/web/app/page.tsx`)
1. Import `Trash2` from `'lucide-react'`.
2. Add a `handleDeleteThread` function:
   - Prevents click propagation (`e.stopPropagation()`).
   - Prompts the user with `window.confirm`.
   - Calls the `DELETE` API.
   - Refreshes state and auto-selects another thread if the deleted one was currently active.
3. Render a delete button (red trash can icon) inside each thread button card:
   - Positioned on the right side.
   - Hidden by default, shown on hover (`opacity-0 group-hover:opacity-100 transition-opacity`).

## 3. Success Criteria
1. Threads can be deleted successfully from the UI.
2. Dependent database records are fully cleared without Foreign Key constraint violations.
3. If the deleted thread is the currently active one, the UI seamlessly falls back to another thread or clears the screen.
4. Biome lint and type check compile successfully with 0 errors.
