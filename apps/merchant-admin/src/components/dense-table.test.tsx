import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  DenseTable,
  DenseTableBody,
  DenseTableCell,
  DenseTableHead,
  DenseTableHeader,
  DenseTableRow,
} from './dense-table';

// 密度预设契约钉:表头/单元格 whitespace-nowrap 是 dense-table 单点职责
// (2026-10-18 用户实弹:全站表格中文竖排折行「满/减」「进行/中」;容器由
// ui Table 的 overflow-auto 包裹承担横向滚动)。caller 经 className 仍可解。

describe('DenseTable(表格密度单点)', () => {
  it('视觉契约:表头/单元格默认 whitespace-nowrap(禁中文竖排折行)', () => {
    render(
      <DenseTable>
        <DenseTableHeader>
          <DenseTableRow>
            <DenseTableHead>订单流水号</DenseTableHead>
          </DenseTableRow>
        </DenseTableHeader>
        <DenseTableBody>
          <DenseTableRow>
            <DenseTableCell>AURORA-ORD-1</DenseTableCell>
          </DenseTableRow>
        </DenseTableBody>
      </DenseTable>,
    );
    expect(screen.getByRole('columnheader', { name: '订单流水号' })).toHaveClass('whitespace-nowrap');
    expect(screen.getByRole('cell', { name: 'AURORA-ORD-1' })).toHaveClass('whitespace-nowrap');
  });
});
