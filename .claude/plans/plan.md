# Implementation Plan - Human-in-the-Loop Conversation Split and Sync Timing Fix

## 1. Problem Description & Root Cause
In the multi-tenant SaaS customer support control panel:
- When a refund is requested, the system suspends execution for administrator approval.
- When an admin on port 3001 approves the refund, the backend database updates the approval status to `approved` and launches `runAgent` in the background (non-blocking) to finish the execution and write the final response.
- The user's screen on port 3000 polls `/api/chat/approvals` every 2 seconds. When it detects a status change (e.g., `waiting` -> `approved`), it triggers `loadHistory(activeThreadId)` to fetch the updated messages.
- **The Timing Race Condition**: Because `runAgent` takes 2–5 seconds to run (calling LLMs, processing the refund, formulating the final response), the frontend's single-turn fetch of message history occurs *before* the new message is physically written.
- Since the status change is only detected once, the frontend never re-fetches history again. The screen remains stuck showing the old history and a spinner.
- Users click "开启新一轮对话" (Start new conversation) or switch merchants out of confusion, splitting the conversation across multiple threads.

---

## 2. Solution Design
We will introduce a **Multi-Turn State Sync Polling Sensor** in the React state:
- Declare a mutable ref `syncPollCountRef = useRef<number>(0)` inside the `Home` component in `apps/web/app/page.tsx`.
- When the 2-second interval poller detects a state transition (`stateChanged === true` from `waiting` to a complete status):
  - Set `syncPollCountRef.current = 6;` (triggering 6 consecutive polls over the next 12 seconds).
  - Call `loadHistory(activeThreadId)` and `fetchThreads()` immediately.
- If `stateChanged` is false, but `syncPollCountRef.current > 0`:
  - Decrement `syncPollCountRef.current -= 1`.
  - Print a log: `[HITL Sync Detector] ⏳ Continuing silent reload of messages and threads. Remaining polls: {syncPollCountRef.current}`.
  - Call `loadHistory(activeThreadId)` and `fetchThreads()`.
- On thread selection changes, reset `syncPollCountRef.current = 0` to prevent cross-thread polling leaks.

---

## 3. Implementation Steps
### Step 1: Update `apps/web/app/page.tsx`
- Add `const syncPollCountRef = useRef<number>(0);` inside `Home` component.
- Update the approvals `useEffect` hook to implement the decremental polling ref.
- Reset the ref when `activeThreadId` changes.

### Step 2: Verification
- Build and run workspace services.
- Verify thread sync flow behaves smoothly without any timing gaps.
