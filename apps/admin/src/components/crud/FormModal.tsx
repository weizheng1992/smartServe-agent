import type React from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  Button,
} from "ui";

export interface FormModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (e: React.FormEvent) => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  submitText?: string;
  isSubmitting?: boolean;
  width?: string;
}

export function FormModal({
  isOpen,
  onClose,
  onSubmit,
  title,
  subtitle,
  children,
  submitText = "保存提交",
  isSubmitting = false,
  width = "max-w-lg",
}: FormModalProps) {
  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => !open && !isSubmitting && onClose()}
    >
      <DialogContent
        className={`w-full ${width} bg-white rounded-2xl shadow-xl border border-slate-200 overflow-hidden p-0 gap-0 z-50`}
      >
        <DialogHeader className="px-6 py-4 border-b border-slate-100 bg-slate-50/60 text-left space-y-0">
          <div>
            <DialogTitle className="text-base font-semibold text-slate-900">
              {title}
            </DialogTitle>
            {subtitle && (
              <DialogDescription className="text-xs text-slate-500 mt-0.5">
                {subtitle}
              </DialogDescription>
            )}
          </div>
        </DialogHeader>

        <form onSubmit={onSubmit}>
          <div className="px-6 py-5 max-h-[70vh] overflow-y-auto space-y-4 text-sm text-slate-700">
            {children}
          </div>

          <DialogFooter className="px-6 py-3.5 border-t border-slate-100 bg-slate-50/60 flex items-center justify-end gap-2.5 sm:space-x-0">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={isSubmitting}
              onClick={onClose}
              className="text-xs font-medium text-slate-600 hover:bg-slate-100"
            >
              取消
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={isSubmitting}
              className="text-xs font-medium bg-slate-900 hover:bg-slate-800 text-white shadow-xs flex items-center gap-1.5"
            >
              {isSubmitting && (
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
              {submitText}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
