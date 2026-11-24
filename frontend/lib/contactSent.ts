// the contact form marks a message the API accepted, so the thank-you page can tell a real send from someone opening its
// address directly. The mark lives for the tab only and is read once.
const KEY = 'phaemos-contact-sent';

export function markContactSent(): void {
  try {
    sessionStorage.setItem(KEY, String(Date.now()));
  } catch {
    // storage can be blocked; the page then says it cannot confirm, which is still true
  }
}

// true when a message was accepted in this tab in the last ten minutes
export function readContactSent(now = Date.now()): boolean {
  try {
    const at = Number(sessionStorage.getItem(KEY));
    return Number.isFinite(at) && at > 0 && now - at < 10 * 60 * 1000;
  } catch {
    return false;
  }
}
