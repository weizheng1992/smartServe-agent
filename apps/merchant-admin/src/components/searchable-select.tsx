import { useState } from 'react';
import {
  Check,
  ChevronsUpDown,
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  Popover,
  PopoverContent,
  PopoverTrigger,
  cn,
} from 'ui';

export interface SearchableOption {
  value: string;
  label: string;
}

interface Props {
  value: string;
  onValueChange: (v: string) => void;
  options: SearchableOption[];
  /** 未选时的触发器文案(空值不回落首项——与 ui Combobox 的 find||options[0] 语义不同) */
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  /** 可达名(getByLabel / getByRole combobox 定位用) */
  ariaLabel: string;
  triggerClassName?: string;
  /** 列表最大高(默认 16rem,超出滚动) */
  listClassName?: string;
}

/** 可搜索下拉(shadcn 官方 combobox 范式 = Popover + Command 组合,ui 原子件):
 * 长列表(商品/指标/员工)搜索定位;列表区 max-h 滚动。短列表请用 ui Select。 */
export function SearchableSelect({
  value,
  onValueChange,
  options,
  placeholder = '请选择…',
  searchPlaceholder = '输入关键词搜索…',
  emptyText = '未找到匹配项',
  ariaLabel,
  triggerClassName,
  listClassName,
}: Props) {
  const [open, setOpen] = useState(false);
  const selected = options.find((o) => o.value === value);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          role="combobox"
          aria-expanded={open}
          aria-label={ariaLabel}
          className={cn(
            'flex h-auto w-fit cursor-pointer items-center justify-between gap-1.5 rounded-lg border border-zinc-300 bg-white px-3 py-2 text-xs font-normal text-zinc-900 shadow-none transition-colors hover:bg-zinc-50',
            triggerClassName,
          )}
        >
          <span className={cn('truncate', !selected && 'text-zinc-400')}>
            {selected ? selected.label : placeholder}
          </span>
          <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 opacity-50" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-72 p-0"
        align="start"
        /* 宿主 Dialog 内:Esc 于 capture 阶段断传播 —— 只收本下拉,不连坐关弹窗
         * (Radix modal/non-modal 分栈,document 级 Esc 会双派发,须在 root 前拦) */
        onKeyDownCapture={(e) => {
          if (e.key === 'Escape') {
            e.stopPropagation();
            setOpen(false);
          }
        }}
      >
        <Command>
          <CommandInput placeholder={searchPlaceholder} />
          <CommandList className={cn('max-h-64 overflow-y-auto', listClassName)}>
            <CommandEmpty>{emptyText}</CommandEmpty>
            <CommandGroup>
              {options.map((o) => (
                <CommandItem
                  key={o.value}
                  value={o.label}
                  onSelect={() => {
                    onValueChange(o.value);
                    setOpen(false);
                  }}
                  className="cursor-pointer"
                >
                  <Check className={cn('h-3.5 w-3.5 shrink-0', o.value === value ? 'opacity-100' : 'opacity-0')} />
                  <span className="truncate">{o.label}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
