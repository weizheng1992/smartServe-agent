import type { MenuNode } from '@/lib/api';
import { toggleNode } from '@/lib/perm-tree';

interface Props {
  nodes: MenuNode[];
  selected: Set<string>;
  onChange: (s: Set<string>) => void;
}

/** 目录/菜单/按钮三级勾选树:勾父带子,子可单独增减(按钮=接口权限点)。
 *  勾选逻辑(collectIds/toggleNode)为纯函数,见 lib/perm-tree.ts。 */
export function PermTree({ nodes, selected, onChange }: Props) {
  const render = (n: MenuNode, depth: number) => (
    <div key={n.id}>
      <label className={`flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-zinc-50 ${n.menuType === 'button' ? 'text-xs text-zinc-500' : 'text-[13px]'}`}>
        <input
          type="checkbox"
          className="accent-zinc-900"
          checked={selected.has(n.id)}
          onChange={(e) => onChange(toggleNode(n, e.target.checked, selected))}
        />
        <span>{n.name}</span>
        {n.menuType === 'button' && n.permCode && (
          <code className="rounded bg-zinc-100 px-1 text-[10px] text-zinc-500">{n.permCode}</code>
        )}
      </label>
      {(n.children || []).length > 0 && (
        <div style={{ paddingLeft: 16 }}>{(n.children || []).map((c) => render(c, depth + 1))}</div>
      )}
    </div>
  );
  return <div className="max-h-72 overflow-y-auto rounded-lg border border-zinc-200 p-2">{nodes.map((n) => render(n, 0))}</div>;
}
