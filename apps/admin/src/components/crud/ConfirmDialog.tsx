import React from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  Button,
} from "ui";

export interface ConfirmDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description: string;
  confirmText?: string;
  cancelText?: string;
  isDestructive?: boolean;
  isLoading?: boolean;
}

export function ConfirmDialog({
  isOpen,
  onClose,
  onConfirm,
  title,
  description,
  confirmText = "确认执行",
  cancelText = "取消",
  isDestructive = true,
  isLoading = false,
}: ConfirmDialogProps) {
  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => !open && !isLoading && onClose()}
    >
      <DialogContent className="w-full max-w-md bg-white rounded-2xl shadow-xl border border-slate-200 overflow-hidden p-6 z-50">
        <DialogHeader className="flex flex-row items-start gap-4 text-left space-y-0">
          <div
            className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${
              isDestructive
                ? "bg-rose-100 text-rose-600"
                : "bg-amber-100 text-amber-600"
            }`}
          >
            <svg
              className="w-5 h-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
              />
            </svg>
          </div>
          <div>
            <DialogTitle className="text-base font-semibold text-slate-900">
              {title}
            </DialogTitle>
            <DialogDescription className="text-xs text-slate-500 mt-1 leading-relaxed">
              {description}
            </DialogDescription>
          </div>
        </DialogHeader>

        <DialogFooter className="mt-6 flex items-center justify-end gap-2.5 sm:space-x-0">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={isLoading}
            onClick={onClose}
            className="text-xs font-medium text-slate-600 hover:bg-slate-100"
          >
            {cancelText}
          </Button>
          <Button
            type="button"
            variant={isDestructive ? "destructive" : "default"}
            size="sm"
            disabled={isLoading}
            onClick={onConfirm}
            className="text-xs font-medium shadow-xs flex items-center gap-1.5"
          >
            {isLoading && (
              <svg
                className="animate-spin w-3.5 h-3.5 text-white"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
            )}
            {confirmText}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
