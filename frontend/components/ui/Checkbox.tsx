import type { InputHTMLAttributes, ReactNode } from 'react';
import { useId } from 'react';
import { cn } from '@/lib/cn';

interface Props extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'children'> {
  label: ReactNode;
  hint?: string;
  className?: string;
}

// the whole row is the label, so the hit area is 44 px high however small the box is. Tick state is shown by the
// browser's own mark, which is a shape and not only a colour.
export default function Checkbox({ label, hint, className, id, ...rest }: Props) {
  const auto = useId();
  const cid = id ?? auto;
  const hintId = hint ? `${cid}-hint` : undefined;
  return (
    <div className={className}>
      <label htmlFor={cid} className={cn('flex min-h-[44px] cursor-pointer items-center gap-3 text-base text-surface-900 dark:text-surface-50', rest.disabled && 'cursor-not-allowed opacity-60')}>
        <input id={cid} type="checkbox" aria-describedby={hintId} {...rest} />
        <span>{label}</span>
      </label>
      {hint && <p id={hintId} className="-mt-1 pl-8 text-base text-surface-600 dark:text-surface-400">{hint}</p>}
    </div>
  );
}
