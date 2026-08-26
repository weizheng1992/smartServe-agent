import React, { useEffect } from 'react';

export interface DetailDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  badge?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: string;
  className?: string;
}

export function DetailDrawer({
  isOpen,
  onClose,
  title,
  subtitle,
  badge,
  children,
  footer,
  width = 'max-w-2xl sm:max-w-3xl lg:max-w-4xl',
  className = '',
}: DetailDrawerProps) {
  // 监听 ESC 按键关闭抽屉 & 锁定页面滚动
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    if (isOpen) {
      document.body.style.overflow = 'hidden';
      window.addEventListener('keydown', handleKeyDown);
    }
    return () => {
      document.body.style.overflow = 'unset';
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className={`fixed inset-0 z-50 overflow-hidden ${className}`}>
      {/* 半透明毛玻璃背景遮罩 */}
      <div
        className="fixed inset-0 bg-slate-900/50 backdrop-blur-xs transition-opacity duration-200"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* 侧边滑出抽屉容器 */}
      <div className="fixed inset-y-0 right-0 max-w-full flex pl-10">
        <div
          className={`w-screen ${width} bg-white shadow-2xl flex flex-col h-full border-l border-slate-200 transform transition ease-in-out duration-300`}
        >
          {/* 顶部标题栏 */}
          <div className="px-6 py-4.5 border-b border-slate-100 bg-slate-50/80 flex items-center justify-between shrink-0">
            <div className="space-y-1">
              <div className="flex items-center gap-2.5">
                <h3 className="text-base font-semibold text-slate-900">{title}</h3>
                {badge}
              </div>
              {subtitle && <p className="text-xs text-slate-500">{subtitle}</p>}
            </div>

            <button
              type="button"
              onClick={onClose}
              className="p-2 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200/60 transition-colors cursor-pointer"
              aria-label="关闭抽屉"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* 抽屉内容主体滚动区 */}
          <div className="flex-1 overflow-y-auto p-6 text-sm text-slate-700 bg-white">{children}</div>

          {/* 底部操作工具栏 */}
          {footer && (
            <div className="px-6 py-4 border-t border-slate-100 bg-slate-50/80 flex items-center justify-end gap-3 shrink-0">
              {footer}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export const Drawer = DetailDrawer;
