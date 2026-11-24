'use client';


import Link from 'next/link';
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from 'react';
import { cn } from '@/lib/cn';
import { useSpinnerVisible } from '@/hooks/useSpinnerVisible';
import { ExternalIcon, SpinnerIcon } from './icons';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize = 'default' | 'small';

// the only button styles. Filled variants carry white text on a background of 5.2:1 or better in both themes and
// the outlined one has a 3:1 border, so a control is findable without colour.
const VARIANTS: Record<ButtonVariant, string> = {
  // brand-700 on light and brand-600 on dark: the dark fill is 3:1 or better against the dark page and the white text is 5:1
  primary: 'bg-brand-700 text-white hover:bg-brand-800 border border-transparent dark:bg-brand-600 dark:hover:bg-brand-700',
  secondary:
    'border border-surface-500 bg-surface-0 text-surface-900 hover:bg-surface-100 dark:bg-surface-900 dark:text-surface-50 dark:hover:bg-surface-800',
  ghost:
    'border border-transparent bg-transparent text-surface-700 hover:bg-surface-100 hover:text-surface-900 dark:text-surface-300 dark:hover:bg-surface-800 dark:hover:text-surface-50',
  danger: 'bg-critical-800 text-white hover:bg-critical-900 border border-transparent',
};

const BASE =
  'relative inline-flex items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap no-underline transition-colors duration-150 ease-out aria-disabled:cursor-not-allowed aria-disabled:opacity-60 disabled:cursor-not-allowed disabled:opacity-60';

// default is 44 px high. Small is 32 px high with a 44 px hit area from an invisible pseudo-element, for dense rows.
// data-hit tells globals.css not to force the 44 px minimum on the element itself.
const SIZES: Record<ButtonSize, string> = {
  default: 'min-h-[44px] min-w-[44px] px-4 text-base',
  small:
    'h-8 min-w-[44px] px-3 text-meta before:absolute before:left-0 before:right-0 before:top-1/2 before:h-11 before:-translate-y-1/2',
};

function classes(variant: ButtonVariant, size: ButtonSize, className?: string): string {
  return cn(BASE, VARIANTS[variant], SIZES[size], className);
}

interface Common {
  variant?: ButtonVariant;
  size?: ButtonSize;
  // work is under way: the label keeps its width, a spinner shows, aria-busy is set and clicks are ignored
  pending?: boolean;
  // the old name for pending
  loading?: boolean;
  icon?: ReactNode;
  children?: ReactNode;
}

// the label and the spinner share one grid cell, so the button never changes width when work starts
function Content({ pending, icon, children }: { pending: boolean; icon?: ReactNode; children?: ReactNode }) {
  // the spinner waits 200 ms and stays at least 300 ms, so a quick action never flashes one
  const spinning = useSpinnerVisible(pending);
  return (
    <span className="inline-grid place-items-center">
      <span className={cn('col-start-1 row-start-1 inline-flex items-center gap-2', spinning && 'invisible')}>
        {icon}
        {children}
      </span>
      {spinning && (
        <span className="col-start-1 row-start-1">
          <SpinnerIcon />
        </span>
      )}
    </span>
  );
}

export type ButtonProps = Common & Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> & { href?: undefined };

export default function Button(props: ButtonProps | LinkButtonProps) {
  if (props.href !== undefined) return <LinkButton {...(props as LinkButtonProps)} />;
  const { variant = 'primary', size = 'default', pending, loading, icon, className, children, onClick, type = 'button', disabled, ...rest } = props as ButtonProps;
  const busy = Boolean(pending ?? loading);
  return (
    <button
      type={type}
      disabled={disabled}
      aria-busy={busy || undefined}
      aria-disabled={busy || undefined}
      data-hit={size === 'small' ? '' : undefined}
      // a pending button stays focusable (aria-disabled, not disabled) and simply ignores the click
      onClick={busy ? (e) => e.preventDefault() : onClick}
      className={classes(variant, size, className)}
      {...rest}
    >
      <Content pending={busy} icon={icon}>{children}</Content>
    </button>
  );
}

export type LinkButtonProps = Common & {
  href: string;
  // opens in a new tab with the safe rel and the external-link mark is the caller's to add
  external?: boolean;
  className?: string;
} & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'children' | 'href' | 'className'>;

// a link that looks like a button. Use it to navigate. Use Button to do something.
export function LinkButton({ href, variant = 'primary', size = 'default', pending, loading, icon, external, className, children, target, rel, ...rest }: LinkButtonProps) {
  const busy = Boolean(pending ?? loading);
  const cls = classes(variant, size, className);
  // a link that opens another site in a new tab carries the external-link mark and says so
  const leaves = external && (target ?? '_blank') === '_blank';
  const content = (
    <Content pending={busy} icon={icon}>
      {children}
      {leaves && (
        <>
          <ExternalIcon />
          <span className="sr-only">(opens in a new tab)</span>
        </>
      )}
    </Content>
  );
  if (external) {
    return (
      <a href={href} target={target ?? '_blank'} rel={rel ?? 'noopener noreferrer'} className={cls} aria-busy={busy || undefined} data-hit={size === 'small' ? '' : undefined} {...rest}>
        {content}
      </a>
    );
  }
  return (
    <Link href={href} className={cls} aria-busy={busy || undefined} data-hit={size === 'small' ? '' : undefined} target={target} rel={rel} {...rest}>
      {content}
    </Link>
  );
}
