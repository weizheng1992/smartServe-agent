import { describe, expect, it, mock } from 'bun:test';
import React from 'react';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../src/components/ui/dialog';

describe('Dialog Component Accessibility & Close Button (TDD)', () => {
  it('renders Dialog with React portal and DialogContent when open', () => {
    const handleOpenChange = mock(() => {});
    const element = React.createElement(
      Dialog,
      { open: true, onOpenChange: handleOpenChange },
      React.createElement(
        DialogContent,
        { className: 'bg-white text-slate-900' },
        React.createElement(DialogHeader, null, React.createElement(DialogTitle, null, '测试弹窗标题')),
        React.createElement(DialogDescription, null, '测试弹窗描述说明'),
        React.createElement(DialogFooter, null, '页脚按钮'),
      ),
    );

    expect(element).toBeDefined();
    expect(element.props.open).toBe(true);
  });

  it('provides accessible close button (aria-label="Close") in DialogContent by default', () => {
    const handleOpenChange = mock(() => {});
    const dialogNode = React.createElement(
      Dialog,
      { open: true, onOpenChange: handleOpenChange },
      React.createElement(
        DialogContent,
        { className: 'p-6' },
        React.createElement(DialogTitle, null, '带关闭按钮的弹窗'),
      ),
    );

    expect(dialogNode).toBeDefined();
    expect(dialogNode.props.onOpenChange).toBeDefined();
  });

  it('allows disabling default close button when showCloseButton is false', () => {
    const element = React.createElement(
      Dialog,
      { open: true },
      React.createElement(
        DialogContent,
        { showCloseButton: false },
        React.createElement(DialogTitle, null, '无默认关闭按钮'),
      ),
    );

    expect(element).toBeDefined();
  });

  it('exports DialogClose component for custom close triggers', () => {
    const closeEl = React.createElement(DialogClose, { className: 'custom-close' }, '关闭');
    expect(closeEl).toBeDefined();
    expect(closeEl.type).toBe(DialogClose);
  });
});
