'use client';

import { Component, ReactNode } from 'react';
import Button, { LinkButton } from './Button';
import { siteHref } from '@/lib/links';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

// use a class component here because React error boundaries require
// componentDidCatch / getDerivedStateFromError, which have no hook equivalent.
export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error) {
    console.error('[ErrorBoundary]', error);
  }

  render() {
    if (this.state.hasError) return <ErrorPanel onReload={() => window.location.reload()} />;
    return this.props.children;
  }
}

// plain and left-aligned: what happened, what to do and where to say it. Shared with app/error.tsx.
export function ErrorPanel({ onReload }: { onReload: () => void }) {
  return (
    <div role="alert" className="mx-auto max-w-xl px-4 py-12 sm:px-6">
      <h1 className="text-xl font-semibold text-surface-900 dark:text-surface-50">This page hit an error</h1>
      <p className="mt-2 text-surface-700 dark:text-surface-300">Reload to try again. If it happens twice, tell us what you were doing.</p>
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <Button onClick={onReload}>Reload</Button>
        <LinkButton href={siteHref('/support')} variant="ghost">Contact support</LinkButton>
      </div>
    </div>
  );
}
