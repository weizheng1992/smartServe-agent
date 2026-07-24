---
description: Next.js frontend and API route guidelines
paths: ["apps/web/**/*"]
---
# Next.js Web App Rules

This workspace handles the user-facing chat UI and light API endpoints.

## Architecture
- **API Entrypoint:** `POST /api/chat` receives messages, starts a job, and returns a `jobId`.
- **SSE Streaming:** `GET /api/chat/[jobId]/stream` serves Server-Sent Events (SSE). It checks if Temporal is available; otherwise, it subscribes to the local LangGraph `agentEventEmitter` to stream progress updates.
- **UI State:** Uses React 19, Tailwind CSS v4, Zustand, and React Query.

## Guidelines
- Avoid heavy computation in Serverless functions to prevent premature timeouts.
- For SSE, always include connection heartbeats to prevent premature gateway termination.
- Keep UI components responsive and match existing styles (Tailwind CSS, custom UI elements).
