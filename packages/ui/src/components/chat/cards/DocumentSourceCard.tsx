'use client';

import type React from 'react';
import type { DocumentSourceCardData, DocumentSourceItem } from 'types';
import { FileText, ImageIcon } from '../../icons';

export interface DocumentSourceCardProps {
  data: DocumentSourceCardData;
}

/** 管道表 markdown → 简易表格(行组切片的表头在每片重复,渲染时天然对齐) */
const renderPipeTable = (markdown: string): React.ReactNode => {
  const rows = markdown
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.startsWith('|'));
  if (rows.length < 2) return null;
  const cells = (line: string) =>
    line
      .split('|')
      .slice(1, -1)
      .map((c) => c.trim());
  const header = cells(rows[0]);
  const body = rows.slice(1).filter((line) => !/^\|[\s:-]+\|$/.test(line));
  return (
    <table className="w-full border-collapse text-xs">
      <thead>
        <tr>
          {/* 表格单元格文本可重复(同值两格/两行同文),key 复合索引防撞名 */}
          {header.map((h, i) => (
            <th
              key={`h-${i}-${h}`}
              className="border border-slate-700 bg-slate-800/60 px-2 py-1 text-left font-semibold text-slate-200"
            >
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {body.map((line, r) => (
          /* biome-ignore lint/suspicious/noArrayIndexKey: 管道表静态渲染不重排无元素状态,单元格文本可重复(同值撞名)才是实害 */
          <tr key={`r-${r}`}>
            {cells(line).map((c, i) => (
              /* biome-ignore lint/suspicious/noArrayIndexKey: 单元格文本可重复,复合索引唯一 */
              <td key={`r${r}-c${i}`} className="border border-slate-700 px-2 py-1 text-slate-300">
                {c}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
};

const ProvenanceBadge: React.FC<{ item: DocumentSourceItem }> = ({ item }) => {
  // 数据诚实律:native=文档原生零误差;extracted/vlm=VLM 读数,必须带误差提示
  if (item.provenance === 'native') {
    return (
      <span className="inline-flex items-center rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-400 ring-1 ring-inset ring-emerald-500/20">
        文档原生数据
      </span>
    );
  }
  if (item.provenance === 'extracted' || item.provenance === 'vlm') {
    return (
      <span className="inline-flex items-center rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-400 ring-1 ring-inset ring-amber-500/20">
        图表读数 · 可能存在误差
      </span>
    );
  }
  return null;
};

export const DocumentSourceCard: React.FC<DocumentSourceCardProps> = ({ data }) => {
  const sources = data.sources || [];
  if (sources.length === 0) return null;

  return (
    <div className="my-2 max-w-md overflow-hidden rounded-xl border border-sky-500/30 bg-gradient-to-b from-sky-950/40 to-slate-900/90 p-4 text-slate-100 shadow-xl backdrop-blur-md">
      <div className="flex items-center gap-2 border-b border-sky-500/20 pb-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-500/10 text-sky-400">
          <FileText className="h-4 w-4" />
        </div>
        <div className="text-xs font-semibold text-sky-300">{data.title || '文档知识来源'}</div>
      </div>
      <div className="flex flex-col gap-3 pt-3">
        {sources.map((item) => (
          <div
            key={`${item.docTitle}:${item.headerPath ?? ''}:${item.imageUrl ?? ''}`}
            className="rounded-lg border border-slate-700/60 bg-slate-800/40 p-2.5"
          >
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-semibold text-slate-200">
                {item.docTitle}
                {item.headerPath ? <span className="font-normal text-slate-400"> · {item.headerPath}</span> : null}
              </div>
              <ProvenanceBadge item={item} />
            </div>
            {item.imageUrl ? (
              <img
                src={item.imageUrl}
                alt={item.docTitle}
                loading="lazy"
                className="mt-2 max-h-48 w-auto rounded-md border border-slate-700"
              />
            ) : null}
            {item.tableMarkdown ? (
              <div className="mt-2 overflow-x-auto">{renderPipeTable(item.tableMarkdown)}</div>
            ) : null}
            {item.snippet ? <p className="mt-2 text-xs leading-relaxed text-slate-400">{item.snippet}</p> : null}
            {item.imageUrl ? (
              <div className="mt-1 flex items-center gap-1 text-[10px] text-slate-500">
                <ImageIcon className="h-3 w-3" />
                <span>图表原图</span>
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
};
