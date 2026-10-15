import '@testing-library/jest-dom/vitest';
import { selectRadixOption } from '@/test/radix-select';
import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { OptionalSelect } from './optional-select';

// 哨兵 invariant 钉(候选③):onChange 直收 '',哨兵 __unset_optional__ 物理上
// 进不了任何 payload —— 此前 6 站点把映射贴在写库边界,写漏一次哨兵即入库,
// 且全仓零测试钉「哨兵不进 payload」。本册把口头律变成 executable contract。

function Harness({ onPick, initial = '' }: { onPick: (v: string) => void; initial?: string }) {
  const [v, setV] = useState(initial);
  return (
    <div>
      <OptionalSelect
        value={v}
        onChange={(x) => {
          setV(x);
          onPick(x);
        }}
        options={[
          { value: '销售部', label: '销售部' },
          { value: '仓储部', label: '仓储部' },
        ]}
        emptyLabel="未分配"
        ariaLabel="部门"
      />
      <span data-testid="current">{v || '(空)'}</span>
    </div>
  );
}

describe('OptionalSelect(哨兵不进 payload)', () => {
  it('选实值:onChange 原样透传', async () => {
    const onPick = vi.fn();
    render(<Harness onPick={onPick} />);
    await selectRadixOption('部门', '销售部');
    expect(onPick).toHaveBeenCalledWith('销售部');
    expect(screen.getByTestId('current')).toHaveTextContent('销售部');
  });

  it('选空值项:onChange 收 ""(非哨兵),哨兵字符串不出现在任何回调里', async () => {
    const onPick = vi.fn();
    // Radix 对「选当前已选项」不触发 onValueChange,且前用例关闭后紧接 pointer
    // 重开会被宽限吞并 —— initial 给实值 + 键盘开层(helper 注明的兜底路径),
    // 单次开层直选空值项,与真实改派流程同构
    render(<Harness onPick={onPick} initial="销售部" />);
    const trigger = screen.getByLabelText('部门');
    trigger.focus();
    fireEvent.keyDown(trigger, { key: 'ArrowDown' });
    const item = await screen.findByRole('option', { name: '未分配' });
    fireEvent.click(item);
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenCalledWith('');
    expect(onPick).not.toHaveBeenCalledWith(expect.stringContaining('__unset'));
    expect(screen.getByTestId('current')).toHaveTextContent('(空)');
  });

  it('鼠标点击之外的受控路径:value="" 恒显空值项文案', () => {
    render(<Harness onPick={() => {}} />);
    expect(screen.getByRole('combobox', { name: '部门' })).toHaveTextContent('未分配');
  });
});
