'use client';

import { Component, type ReactNode } from 'react';

interface Props {
  // what the chart shows, so the message can name it
  name: string;
  children: ReactNode;
}

// one chart that fails to draw must not take the page down. The message names the chart and says what to do.
export default class ChartBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error) {
    console.error('[chart]', error);
  }

  render() {
    if (this.state.failed) {
      return (
        <div role="alert" className="py-3 text-sm text-surface-900 dark:text-surface-50">
          <p className="font-medium">The {this.props.name.toLowerCase()} chart could not be drawn.</p>
          <p className="mt-1 text-surface-700 dark:text-surface-300">Reload the page. The readings are still stored and appear in the latest readings table.</p>
        </div>
      );
    }
    return this.props.children;
  }
}
