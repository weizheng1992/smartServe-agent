import * as React from 'react';
import { cn } from '../../lib/utils';

export interface ScrollAreaProps extends React.HTMLAttributes<HTMLDivElement> {}

const ScrollArea = React.forwardRef<HTMLDivElement, ScrollAreaProps>(({ className, children, ...props }, ref) => {
  return (
    <div ref={ref} className={cn('relative overflow-auto', className)} {...props}>
      <div className="h-full w-full rounded-[inherit]">{children}</div>
    </div>
  );
});
ScrollArea.displayName = 'ScrollArea';

export { ScrollArea };
