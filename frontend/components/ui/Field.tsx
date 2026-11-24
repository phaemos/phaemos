import { useId, type ReactNode } from 'react';
import { cn } from '@/lib/cn';

// what a control needs to be tied to its label, hint and error
export interface FieldControlProps {
  id: string;
  'aria-describedby'?: string;
  'aria-invalid'?: true;
  'aria-required'?: true;
}

interface Props {
  label: string;
  // a render function gets the props to spread on the control. Input, Select and Textarea do this for you.
  children: (control: FieldControlProps) => ReactNode;
  id?: string;
  hint?: string;
  // a message in words. Setting it marks the control invalid.
  error?: string;
  required?: boolean;
  className?: string;
}

// a label tied to its control by id, an optional hint and an optional error. The error is text, so a failed field
// is never signalled by colour alone. aria-describedby points at it.
export default function Field({ label, children, id, hint, error, required, className }: Props) {
  const auto = useId();
  const controlId = id ?? auto;
  const hintId = hint ? `${controlId}-hint` : undefined;
  const errorId = error ? `${controlId}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined;

  return (
    <div className={cn('space-y-1.5', className)}>
      <label htmlFor={controlId} className="block text-base font-medium text-surface-900 dark:text-surface-50">
        {label}
        {required && <span className="font-normal text-surface-600 dark:text-surface-400"> (required)</span>}
      </label>
      {hint && <p id={hintId} className="text-base text-surface-600 dark:text-surface-400">{hint}</p>}
      {children({ id: controlId, 'aria-describedby': describedBy, 'aria-invalid': error ? true : undefined, 'aria-required': required ? true : undefined })}
      {error && <p id={errorId} className="text-base font-medium text-critical-800 dark:text-critical-300">{error}</p>}
    </div>
  );
}
