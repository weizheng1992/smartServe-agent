import { describe, expect, it } from 'bun:test';
import React from 'react';
import { renderToString } from 'react-dom/server';
import { MessageText } from '../src/components/chat/MessageText';

// 真实事故载荷(2026-09-25,aurora 商户门户):客服 bot 对「几个帐篷的特点和
// 价格对比,给一个表格」产出的 GFM 管道表。四面聊天 UI 全部纯文本
// whitespace-pre-wrap 渲染,用户看到的是竖线原文——「没有表格渲染」。
const INCIDENT_TEXT = `尊敬的顾客，您好！

根据您的要求，以下是帐篷的特点和价格对比表格：

| 帐篷型号 | 特点 | 价格（¥） |
|----------------|------------------------------------------------------------|-----------|
| 极光 轻量化双人双层露营帐篷 | 轻便便携，20D硅涂尼龙外帐防水3000mm，3分钟快速搭建 | 1299.00   |
| 极光帐篷A款 | 轻便便携，适合短期户外露营 | 399.00    |

以上帐篷均具有各自的特色和适用场景。`;

describe('MessageText GFM 表格渲染', () => {
  it('事故载荷:管道表必须渲染为语义 <table>(症状「没有表格渲染」)', () => {
    const html = renderToString(<MessageText text={INCIDENT_TEXT} />);
    expect(html).toContain('<table');
    expect(html).toContain('<th');
    expect(html).toContain('帐篷型号');
    expect(html).toContain('<td');
    expect(html).toContain('极光 轻量化双人双层露营帐篷');
    expect(html).toContain('1299.00');
    expect(html).toContain('极光帐篷A款');
    // 表格行不得再以竖线原文形式出现
    expect(html).not.toContain('| 极光帐篷A款');
  });

  it('混合内容:表格外段落逐字保留(含换行)', () => {
    const html = renderToString(<MessageText text={INCIDENT_TEXT} />);
    expect(html).toContain('尊敬的顾客，您好！');
    expect(html).toContain('以上帐篷均具有各自的特色和适用场景。');
  });

  it('分隔行决定列对齐(:--- 左 / ---: 右)', () => {
    const html = renderToString(<MessageText text={'| 商品 | 库存 |\n|:-----|-----:|\n| 帐篷 | 12   |'} />);
    expect(html).toContain('text-align:left');
    expect(html).toContain('text-align:right');
  });

  it('无分隔行的管道块是诚实降级:保持纯文本,不硬造表格', () => {
    const text = '| 只是恰好以竖线开头的一行 |\n| 第二行也不是分隔行 |';
    const html = renderToString(<MessageText text={text} />);
    expect(html).not.toContain('<table');
    expect(html).toContain('| 只是恰好以竖线开头的一行 |');
  });

  it('分隔行列数与表头不符:不渲染表格(防误判)', () => {
    const text = '| A | B |\n|---|---|---|\n| 1 | 2 | 3 |';
    const html = renderToString(<MessageText text={text} />);
    expect(html).not.toContain('<table');
  });

  it('纯文本零表格:与旧直通渲染逐字等价(不回归既有消息)', () => {
    const text = '您好，请问需要什么帮助？\n第二行文字';
    const html = renderToString(<MessageText text={text} />);
    expect(html).not.toContain('<table');
    expect(html).toContain('您好，请问需要什么帮助？');
    expect(html).toContain('第二行文字');
  });
});
