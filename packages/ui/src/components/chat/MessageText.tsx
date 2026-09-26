/**
 * MessageText — 聊天气泡文本渲染(零依赖 GFM 管道表)。
 *
 * 动机(2026-09-25 aurora 事故):客服 bot 对「给一个表格」产出 GFM 管道表,
 * 四个聊天面(merchant 悬浮助手 / web ChatArea / merchant-admin 直播台 /
 * admin 深溯抽屉)全部纯文本 whitespace-pre-wrap 渲染,用户看到竖线原文
 * ——「没有表格渲染」。全仓禁重型 markdown 依赖(CLAUDE.md §5 零依赖共享
 * UI),故在此手写最小 GFM 子集:仅「表头 + 分隔行 + 若干数据行」的管道
 * 表升级为语义 <table>,其余内容逐字保留。
 *
 * 诚实降级契约:缺分隔行、分隔行列数与表头不符、行首竖线但不成表 ——
 * 一律原样纯文本,严禁硬造表格。
 */

type ColAlign = 'left' | 'center' | 'right';

type TextBlock = { kind: 'text'; text: string };
type TableBlock = { kind: 'table'; header: string[]; rows: string[][]; aligns: ColAlign[] };
type Block = TextBlock | TableBlock;

/** 拆一行管道行为首尾竖线剥离后的单元格(不做 \| 转义,bot 输出未见该形态)。 */
function splitRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith('|')) s = s.slice(1);
  if (s.endsWith('|')) s = s.slice(0, -1);
  return s.split('|').map((c) => c.trim());
}

/** GFM 分隔行单元格:`---` / `:---` / `---:` / `:---:`(至少一个连字符)。 */
function separatorAlign(cell: string): ColAlign | null {
  const m = /^(:?)(-+)(:?)$/.exec(cell);
  if (!m) return null;
  if (m[1] && m[3]) return 'center';
  if (m[3]) return 'right';
  return 'left';
}

function isSeparatorRow(cells: string[]): boolean {
  return cells.length > 0 && cells.every((c) => separatorAlign(c) !== null);
}

/** 把文本切成 text/table 块序列;text 块逐字保留(含换行,由 pre-wrap 呈现)。 */
function parseBlocks(text: string): Block[] {
  const lines = text.split('\n');
  const blocks: Block[] = [];
  let buf: string[] = [];
  const flush = () => {
    if (buf.length > 0) {
      blocks.push({ kind: 'text', text: buf.join('\n') });
      buf = [];
    }
  };
  let i = 0;
  while (i < lines.length) {
    const trimmed = lines[i].trim();
    const next = i + 1 < lines.length ? splitRow(lines[i + 1]) : null;
    if (trimmed.startsWith('|') && next && isSeparatorRow(next)) {
      const header = splitRow(trimmed);
      // 表头与分隔行列数必须一致,否则不成表(GFM 规范,防误判)
      if (header.length === next.length) {
        const rows: string[][] = [];
        let j = i + 2;
        while (j < lines.length && lines[j].trim().startsWith('|')) {
          rows.push(splitRow(lines[j]));
          j += 1;
        }
        flush();
        blocks.push({ kind: 'table', header, rows, aligns: next.map((c) => separatorAlign(c) as ColAlign) });
        i = j;
        continue;
      }
    }
    buf.push(lines[i]);
    i += 1;
  }
  flush();
  return blocks;
}

const ALIGN_CLASS: Record<ColAlign, string> = {
  left: 'text-left',
  center: 'text-center',
  right: 'text-right',
};

export interface MessageTextProps {
  text: string;
  /** 追加到每个文本块上的类(气泡面传入 whitespace-pre-wrap 等排版类)。 */
  className?: string;
}

export function MessageText({ text, className }: MessageTextProps) {
  const blocks = parseBlocks(text);
  return (
    <>
      {blocks.map((block, idx) =>
        block.kind === 'text' ? (
          // biome-ignore lint/suspicious/noArrayIndexKey: 块序列纯静态派生自 text,无重排
          <div key={idx} className={className}>
            {block.text}
          </div>
        ) : (
          // biome-ignore lint/suspicious/noArrayIndexKey: 同上
          <div key={idx} className="my-1 overflow-x-auto">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr>
                  {block.header.map((cell, c) => (
                    <th
                      /* biome-ignore lint/suspicious/noArrayIndexKey: 静态表头,无重排 */
                      key={c}
                      style={{ textAlign: block.aligns[c] }}
                      className={`border border-slate-200 bg-slate-50 px-2 py-1 font-medium text-slate-600 ${ALIGN_CLASS[block.aligns[c]]}`}
                    >
                      {cell}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {block.rows.map((row, r) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: 静态回放行,无重排
                  <tr key={r}>
                    {row.map((cell, c) => (
                      <td
                        /* biome-ignore lint/suspicious/noArrayIndexKey: 静态回放行,无重排 */
                        key={c}
                        style={{ textAlign: block.aligns[c] }}
                        className={`border border-slate-200 px-2 py-1 text-slate-800 ${ALIGN_CLASS[block.aligns[c]]}`}
                      >
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ),
      )}
    </>
  );
}
