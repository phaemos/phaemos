// turns a failed request into one plain sentence a person can act on. The raw library message (for example
// "Request failed with status code 500") never reaches the screen.
import axios from 'axios';

export function describeApiError(err: unknown, what = 'The request'): string {
  if (axios.isAxiosError(err)) {
    const status = err.response?.status;
    if (!err.response) return 'Could not reach the server. Check your connection and try again.';
    if (status === 403) return 'Your account is not allowed to do that. Ask an administrator if you need access.';
    if (status === 404) return `${what} could not be found. It may have been removed or you may not have access to it.`;
    if (status === 422) return `${what} was not accepted. Check the address or the values you entered and try again.`;
    if (status === 429) return 'Too many requests. Wait a moment and try again.';
    if (status && status >= 500) return 'The server had a problem with that. Try again in a moment.';
  }
  return `${what} did not complete. Try again.`;
}
