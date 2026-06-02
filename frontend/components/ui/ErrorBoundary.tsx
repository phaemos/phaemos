'use client';

import { Component, ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

// I use a class component here because React error boundaries require
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
    if (this.state.hasError) {
      return (
        <div className="card flex flex-col items-center justify-center py-16 px-4 text-center m-4">
          <span className="text-5xl mb-4">⚠</span>
          <h3 className="text-lg font-semibold text-surface-900 dark:text-surface-50 mb-1">
            Something went wrong
          </h3>
          <p className="text-sm text-surface-400 dark:text-surface-500 mb-4">
            An unexpected error occurred. Refreshing the page usually fixes it.
          </p>
          <button
            onClick={() => window.location.reload()}
            className="bg-brand-600 hover:bg-brand-700 active:scale-95 text-white px-4 py-2 rounded-lg text-sm font-medium transition-all duration-150"
          >
            Refresh page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
