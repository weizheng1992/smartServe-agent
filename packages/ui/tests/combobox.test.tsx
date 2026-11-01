import { describe, expect, it } from 'bun:test';
import React from 'react';
import { renderToString } from 'react-dom/server';
import { Combobox } from '../src/components/ui/combobox';

const OPTIONS = [
  { value: 'aurora', label: '极光潮品', badge: 'aurora' },
  { value: 'nike', label: 'Nike 旗舰店' },
];

function renderTrigger(props: React.ComponentProps<typeof Combobox>) {
  return renderToString(<Combobox {...props} />);
}

describe('Combobox 触发器标签诚实性(2026-10-31 假标签收口)', () => {
  it('未选(value 缺省)显示 placeholder,严禁回落首项假标签', () => {
    const html = renderTrigger({ options: OPTIONS });
    expect(html).toContain('请选择...');
    expect(html).not.toContain('极光潮品');
    expect(html).not.toContain('Nike 旗舰店');
  });

  it('value 匹配选项时显示对应 label 与 badge', () => {
    const html = renderTrigger({ options: OPTIONS, value: 'aurora' });
    expect(html).toContain('极光潮品');
    expect(html).toContain('aurora');
    expect(html).not.toContain('Nike 旗舰店');
  });

  it('value 不在 options 内(数据面异常)显示 placeholder,不伪装首项', () => {
    const html = renderTrigger({ options: OPTIONS, value: 'ghost-tenant' });
    expect(html).toContain('请选择...');
    expect(html).not.toContain('极光潮品');
  });
});
