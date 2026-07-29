# Plan: Migrate Shared UI Components to `packages/ui` and Remove `lucide-react`

This plan outlines the steps to extract and encapsulate our shared shadcn UI components into a dedicated, monorepo-wide public workspace package `packages/ui` and completely remove the external dependency `lucide-react`, substituting all required icons with custom, highly optimized, typed SVG icon components exported directly from the same package.

---

## 1. Create Shared Workspace Package: `packages/ui`

We will create a clean and standard private package `ui` in the monorepo workspaces:

### 1.1 `packages/ui/package.json`
```json
{
  "name": "ui",
  "version": "0.1.0",
  "private": true,
  "main": "src/index.ts",
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "clsx": "^2.1.1",
    "tailwind-merge": "^3.6.0"
  }
}
```

### 1.2 `packages/ui/tsconfig.json`
```json
{
  "compilerOptions": {
    "target": "es2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true
  },
  "include": ["src"]
}
```

### 1.3 `packages/ui/src/lib/utils.ts`
Replicate the standard Tailwind ClassNames merger helper:
```typescript
import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

---

## 2. Extract and Package shadcn UI Components

We will move the shadcn components currently located under `apps/web/components/ui/` to `packages/ui/src/components/ui/` and adapt their relative imports:

1. **`button.tsx`**: Update import of `cn` to `../../lib/utils`
2. **`card.tsx`**: Update import of `cn` to `../../lib/utils`
3. **`badge.tsx`**: Update import of `cn` to `../../lib/utils`
4. **`input.tsx`**: Update import of `cn` to `../../lib/utils`
5. **`scroll-area.tsx`**: Update import of `cn` to `../../lib/utils`
6. **`avatar.tsx`**: Update import of `cn` to `../../lib/utils`

---

## 3. Package Standard Lightweight Icons (`packages/ui/src/components/icons.tsx`)

We will author custom, performant, SVG-based React component representations for the 27 icons currently imported from `lucide-react`:

* **Icons**: `Activity`, `ArrowRight`, `CheckCircle2`, `Clock`, `Cpu`, `ImageIcon` (represented as standard Image), `Laptop`, `Layout`, `Loader2` (adds standard spin animation), `LogOut`, `Maximize2`, `MessageSquare`, `Plus`, `RefreshCw` (adds spin animation/support), `Send`, `Shield`, `Sparkles`, `Trash2`, `User`, `X`, `XCircle`, `DollarSign`, `Layers`, `Lock`, `Search`, `ShieldAlert`, `TrendingUp`.

---

## 4. Export Interface (`packages/ui/src/index.ts`)

Export everything from our entry point:
```typescript
export * from './components/ui/button';
export * from './components/ui/card';
export * from './components/ui/badge';
export * from './components/ui/input';
export * from './components/ui/scroll-area';
export * from './components/ui/avatar';
export * from './components/icons';
export * from './lib/utils';
```

---

## 5. Register Shared Package in Apps

Add `"ui": "workspace:*"` to `dependencies` in:
- `apps/web/package.json`
- `apps/admin/package.json`

Run `bun install` to symlink and register the workspace.

---

## 6. Uninstall `lucide-react`

Remove `"lucide-react"` from `apps/web/package.json` and `apps/admin/package.json`.

---

## 7. Refactor Apps to Consume Shared Package

1. Remove any custom local component folders inside `apps/web/components/ui/` to prevent dual-compilation conflicts.
2. In the following page/component files:
   * `apps/web/app/page.tsx`
   * `apps/web/app/login/page.tsx`
   * `apps/web/components/login-card.tsx`
   * `apps/admin/app/page.tsx`
   * Rewrite imports of components (e.g. `Button`, `Card`, `Badge`, `Input`, `Avatar`, `ScrollArea`) to point to `"ui"`.
   * Rewrite imports of all icons (e.g. `Send`, `Trash2`, `Sparkles`) to point to `"ui"`.

---

## 8. Build, Lint, and Verify

Run `bun run build` and `bun run lint` to guarantee 100% type safety and linting compliance across the monorepo workspace.
