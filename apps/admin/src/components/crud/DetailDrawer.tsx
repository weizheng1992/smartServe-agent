import type React from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetFooter,
} from "ui";

export interface DetailDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  badge?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: string;
}

export function DetailDrawer({
  isOpen,
  onClose,
  title,
  subtitle,
  badge,
  children,
  footer,
  width = "sm:max-w-2xl",
}: DetailDrawerProps) {
  return (
    <Sheet open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <SheetContent
        side="right"
        className={`w-full ${width} bg-white shadow-2xl flex flex-col h-full border-l border-slate-200 p-0 gap-0 z-50`}
      >
        {/* 顶部标题区 */}
        <SheetHeader className="px-5 py-4 border-b border-slate-100 bg-slate-50/50 flex flex-row items-center justify-between text-left space-y-0 pr-12">
          <div className="flex items-center gap-3">
            <div>
              <div className="flex items-center gap-2">
                <SheetTitle className="text-base font-semibold text-slate-900">
                  {title}
                </SheetTitle>
                {badge}
              </div>
              {subtitle && (
                <SheetDescription className="text-xs text-slate-500 mt-0.5">
                  {subtitle}
                </SheetDescription>
              )}
            </div>
          </div>
        </SheetHeader>

        {/* 抽屉内容区 */}
        <div className="flex-1 overflow-y-auto p-5 text-sm text-slate-700 bg-white">
          {children}
        </div>

        {/* 底部操作区 */}
        {footer && (
          <SheetFooter className="px-5 py-3.5 border-t border-slate-100 bg-slate-50/50 flex items-center justify-end gap-2.5 sm:space-x-0">
            {footer}
          </SheetFooter>
        )}
      </SheetContent>
    </Sheet>
  );
}
