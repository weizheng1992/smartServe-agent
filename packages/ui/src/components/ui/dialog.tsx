'use client';

import * as React from 'react';
import { createPortal } from 'react-dom';
import { cn } from '../../lib/utils';
import { X } from '../icons';

export interface DialogProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
}

interface DialogContextValue {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

const DialogContext = React.createContext<DialogContextValue>({});

export const useDialog = () => React.useContext(DialogContext);

const Dialog: React.FC<DialogProps> = ({ open = false, onOpenChange, children }) => {
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => {
    setMounted(true);
  }, []);

  React.useEffect(() => {
    if (!open) return;

    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onOpenChange?.(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      document.body.style.overflow = originalOverflow;
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [open, onOpenChange]);

  if (!open) return null;

  const content = (
    <DialogContext.Provider value={{ open, onOpenChange }}>
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 animate-in fade-in duration-200"
        onClick={(e) => {
          if (e.target === e.currentTarget) {
            onOpenChange?.(false);
          }
        }}
      >
        {children}
      </div>
    </DialogContext.Provider>
  );

  if (mounted && typeof document !== 'undefined') {
    return createPortal(content, document.body);
  }

  return content;
};

export interface DialogContentProps extends React.HTMLAttributes<HTMLDivElement> {
  showCloseButton?: boolean;
  onClose?: () => void;
}

const DialogContent = React.forwardRef<HTMLDivElement, DialogContentProps>(
  ({ className, children, showCloseButton = true, onClose, ...props }, ref) => {
    const { onOpenChange } = useDialog();

    const handleClose = () => {
      if (onClose) {
        onClose();
      } else {
        onOpenChange?.(false);
      }
    };

    return (
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        className={cn(
          'relative w-full max-w-lg bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl animate-in zoom-in-95 duration-200 flex flex-col max-h-[90vh] overflow-hidden',
          className,
        )}
        onClick={(e) => e.stopPropagation()}
        {...props}
      >
        {children}

        {showCloseButton && (
          <button
            type="button"
            aria-label="Close"
            onClick={handleClose}
            className="absolute right-4 top-4 rounded-lg p-1.5 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors z-20 cursor-pointer focus:outline-hidden focus:ring-2 focus:ring-slate-400"
          >
            <X className="h-4 w-4" />
            <span className="sr-only">Close</span>
          </button>
        )}
      </div>
    );
  },
);
DialogContent.displayName = 'DialogContent';

const DialogClose = React.forwardRef<HTMLButtonElement, React.ButtonHTMLAttributes<HTMLButtonElement>>(
  ({ className, onClick, ...props }, ref) => {
    const { onOpenChange } = useDialog();
    return (
      <button
        ref={ref}
        type="button"
        aria-label="Close"
        onClick={(e) => {
          onClick?.(e);
          onOpenChange?.(false);
        }}
        className={cn(
          'rounded-lg p-1.5 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer',
          className,
        )}
        {...props}
      />
    );
  },
);
DialogClose.displayName = 'DialogClose';

const DialogHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'flex flex-col space-y-1.5 text-center sm:text-left pb-4 border-b border-slate-100 dark:border-slate-800 shrink-0 pr-8',
        className,
      )}
      {...props}
    />
  ),
);
DialogHeader.displayName = 'DialogHeader';

const DialogFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2 pt-4 border-t border-slate-100 dark:border-slate-800 shrink-0',
        className,
      )}
      {...props}
    />
  ),
);
DialogFooter.displayName = 'DialogFooter';

const DialogTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h3
      ref={ref}
      className={cn('text-lg font-semibold leading-none tracking-tight text-slate-900 dark:text-slate-100', className)}
      {...props}
    />
  ),
);
DialogTitle.displayName = 'DialogTitle';

const DialogDescription = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(
  ({ className, ...props }, ref) => (
    <p ref={ref} className={cn('text-sm text-slate-500 dark:text-slate-400', className)} {...props} />
  ),
);
DialogDescription.displayName = 'DialogDescription';

export { Dialog, DialogContent, DialogClose, DialogHeader, DialogFooter, DialogTitle, DialogDescription };
