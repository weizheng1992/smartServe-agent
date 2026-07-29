# Implementation Plan - Restoring Container Scrollability and Styles

To resolve container-level rendering and scrolling bugs inside the chat window and the APM monitor sidebar, we will:

1. **Revert the global shared ScrollArea component** back to its original implementation. Changing global components can break layout assumptions elsewhere.
2. **Replace ScrollArea in the main chat area with a native `div` using Tailwind CSS flexbox constraints (`flex-1 overflow-y-auto p-6 min-h-0`)**. This guarantees vertical scrolling, protects against browser box model height lock-ups, and is fully compatible with standard `scrollIntoView()` on our messages end anchor.
3. **Refactor the right-side execution trace panel (`section`)** to avoid double scrollbars and ensure pixel-perfect scrollability on all screens:
   - Change `overflow-y-auto` to `overflow-hidden` on the outer `section` container.
   - Convert `<div className="space-y-6">` into a dynamic flexbox layout: `space-y-6 flex-1 flex flex-col min-h-0 mb-4`.
   - Prevent the header elements from shrinking with `shrink-0`.
   - Replace `<ScrollArea className="h-[70vh] pr-2">` with `<div className="flex-1 overflow-y-auto pr-2 min-h-0">` to allow dynamic native vertical scrolling.
   - Retain the bottom status/billing card anchored perfectly at the bottom of the section.

## Verification Checklist

- [ ] Revert `packages/ui/src/components/ui/scroll-area.tsx` and verify correct syntax.
- [ ] Replace `ScrollArea` with native `div` in main chat area in `apps/web/app/page.tsx`.
- [ ] Refactor Right Execution Detail Logging Panel to use native flexbox scrolling instead of h-[70vh] ScrollArea.
- [ ] Run linter `bun run lint` to verify everything compiles cleanly without any errors.
