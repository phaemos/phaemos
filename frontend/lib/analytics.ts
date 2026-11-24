// one way to send a Google Analytics event. It does nothing unless the tag is on the page, which happens only after a visitor
// accepts analytics (components/GoogleAnalytics.tsx), so a call is always safe. Events carry fixed names and fixed words only:
// never what a person typed, an email address, a machine id or an address with a query string.
type EventName = 'contact_message_sent' | 'repository_opened' | 'docs_opened';

export function track(name: EventName, params: Record<string, string> = {}): void {
  if (typeof window === 'undefined') return;
  const gtag = (window as unknown as { gtag?: (...args: unknown[]) => void }).gtag;
  if (typeof gtag !== 'function') return;
  try {
    gtag('event', name, params);
  } catch {
    // counting is never a reason for a page to fail
  }
}
