import * as React from 'react';
import { cn } from '../../lib/utils';
import { Check, ChevronsUpDown } from '../icons';
import { Button } from './button';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from './command';
import { Popover, PopoverContent, PopoverTrigger } from './popover';

export interface ComboboxOption {
  value: string;
  label: string;
  badge?: string;
  badgeColor?: string;
}

export interface ComboboxProps {
  options: ComboboxOption[];
  value?: string;
  onChange?: (val: string) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  className?: string;
  triggerClassName?: string;
  contentClassName?: string;
  label?: string;
  compact?: boolean;
}

export function Combobox({
  options = [],
  value,
  onChange,
  placeholder = '请选择...',
  searchPlaceholder = '输入关键词搜索...',
  emptyText = '未找到匹配项',
  className,
  triggerClassName,
  contentClassName,
  label,
  compact = false,
}: ComboboxProps) {
  const [open, setOpen] = React.useState(false);

  const selectedOption = React.useMemo(() => {
    return options.find((opt) => opt.value === value) || options[0];
  }, [options, value]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className={cn(
            'justify-between bg-slate-50 hover:bg-slate-100/80 border-slate-200 text-slate-800 font-normal transition-all',
            compact ? 'h-7 px-2.5 text-xs' : 'h-8 px-3 text-xs',
            triggerClassName,
            className,
          )}
        >
          <div className="flex items-center gap-1.5 truncate max-w-[220px]">
            {label && <span className="text-[11px] font-medium text-slate-500 whitespace-nowrap">{label}</span>}
            <span className="font-semibold text-slate-800 truncate">
              {selectedOption ? selectedOption.label : placeholder}
            </span>
            {selectedOption?.badge && (
              <span
                className={cn(
                  'text-[10px] px-1.5 py-0.2 rounded font-mono border whitespace-nowrap',
                  selectedOption.badgeColor || 'bg-slate-100 text-slate-600 border-slate-300',
                )}
              >
                {selectedOption.badge}
              </span>
            )}
          </div>
          <ChevronsUpDown className="ml-1.5 h-3.5 w-3.5 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className={cn('w-72 p-0 shadow-xl border-slate-200', contentClassName)} align="start">
        <Command>
          <CommandInput placeholder={searchPlaceholder} />
          <CommandList>
            <CommandEmpty>{emptyText}</CommandEmpty>
            <CommandGroup>
              {options.map((option) => {
                const isSelected = option.value === value;
                return (
                  <CommandItem
                    key={option.value}
                    value={`${option.label} ${option.value}`}
                    onSelect={() => {
                      onChange?.(option.value);
                      setOpen(false);
                    }}
                    className="flex items-center justify-between"
                  >
                    <div className="flex flex-col min-w-0 pr-2">
                      <span className="truncate font-medium text-slate-900">{option.label}</span>
                      <span className="text-[10px] text-slate-400 font-mono mt-0.5">ID: {option.value}</span>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {option.badge && (
                        <span
                          className={cn(
                            'text-[10px] px-1.5 py-0.2 rounded font-mono border',
                            option.badgeColor || 'bg-slate-100 text-slate-600 border-slate-300',
                          )}
                        >
                          {option.badge}
                        </span>
                      )}
                      <Check
                        className={cn(
                          'h-4 w-4 text-slate-900 transition-opacity',
                          isSelected ? 'opacity-100' : 'opacity-0',
                        )}
                      />
                    </div>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
