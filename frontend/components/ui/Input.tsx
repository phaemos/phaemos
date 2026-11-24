import { useState, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react';
import { cn } from '@/lib/cn';
import Field from './Field';
import { EyeIcon, EyeOffIcon, SearchIcon } from './icons';

// one control style: 44 px high, a 3:1 border, 6 px corners and the global focus ring. An invalid control also
// gets a heavier critical border, on top of the error text that Field prints.
const CONTROL =
  'block w-full rounded-md border bg-surface-0 px-3 text-base text-surface-900 placeholder:text-surface-600 dark:bg-surface-900 dark:text-surface-50 dark:placeholder:text-surface-400 disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-2 aria-[invalid=true]:border-critical-700 dark:aria-[invalid=true]:border-critical-400';

interface FieldProps {
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  // classes for the wrapper, className goes on the control
  wrapperClassName?: string;
}

export function Input({ label, hint, error, required, wrapperClassName, className, id, ...rest }: FieldProps & Omit<InputHTMLAttributes<HTMLInputElement>, 'required'>) {
  // a search field carries a magnifier, so it is recognised before anyone reads its label
  const search = rest.type === 'search';
  return (
    <Field label={label} hint={hint} error={error} required={required} id={id} className={wrapperClassName}>
      {(c) => (
        <div className="relative">
          {search && (
            <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-surface-700 dark:text-surface-300" aria-hidden="true"><SearchIcon /></span>
          )}
          <input {...c} required={required} className={cn(CONTROL, 'min-h-[44px] py-2', search && 'pl-10', className)} {...rest} />
        </div>
      )}
    </Field>
  );
}

// a password field with a show and hide button. The button names what pressing it does and reports its state.
export function PasswordInput({ label, hint, error, required, wrapperClassName, className, id, ...rest }: FieldProps & Omit<InputHTMLAttributes<HTMLInputElement>, 'required' | 'type'>) {
  const [shown, setShown] = useState(false);
  return (
    <Field label={label} hint={hint} error={error} required={required} id={id} className={wrapperClassName}>
      {(c) => (
        <div className="relative">
          <input {...c} type={shown ? 'text' : 'password'} required={required} className={cn(CONTROL, 'min-h-[44px] py-2 pr-12', className)} {...rest} />
          <button
            type="button"
            onClick={() => setShown((v) => !v)}
            aria-label={shown ? 'Hide password' : 'Show password'}
            className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-md text-surface-700 hover:text-surface-900 dark:text-surface-300 dark:hover:text-surface-50"
          >
            {shown ? <EyeOffIcon /> : <EyeIcon />}
          </button>
        </div>
      )}
    </Field>
  );
}

export function Textarea({ label, hint, error, required, wrapperClassName, className, id, rows = 4, ...rest }: FieldProps & Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'required'>) {
  return (
    <Field label={label} hint={hint} error={error} required={required} id={id} className={wrapperClassName}>
      {(c) => <textarea {...c} rows={rows} required={required} className={cn(CONTROL, 'py-2', className)} {...rest} />}
    </Field>
  );
}

export function Select({ label, hint, error, required, wrapperClassName, className, id, children, ...rest }: FieldProps & Omit<SelectHTMLAttributes<HTMLSelectElement>, 'required'> & { children: ReactNode }) {
  return (
    <Field label={label} hint={hint} error={error} required={required} id={id} className={wrapperClassName}>
      {(c) => <select {...c} required={required} className={cn(CONTROL, 'min-h-[44px] py-2', className)} {...rest}>{children}</select>}
    </Field>
  );
}

export default Input;
