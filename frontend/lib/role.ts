// the role claim inside the access token, for deciding which controls to offer. This is only a hint for the
// interface: the API checks the role again on every request, so a forged token gains no access.

export type Role = 'admin' | 'technician' | 'viewer';

export function roleFromToken(token: string | null | undefined): Role | null {
  if (!token) return null;
  const part = token.split('.')[1];
  if (!part) return null;
  try {
    // tokens use the URL-safe alphabet without padding
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/');
    const role = JSON.parse(atob(b64.padEnd(Math.ceil(b64.length / 4) * 4, '='))).role;
    return role === 'admin' || role === 'technician' || role === 'viewer' ? role : null;
  } catch {
    return null;
  }
}

// a viewer reads and never changes: the API answers 403 to a viewer who resolves an alert or creates or edits a ticket;
// while the role is not known yet (the first render or a token that cannot be read) the answer is no, so a control for
// writing never flashes for a viewer. The API still decides every request.
export function canWrite(role: Role | null): boolean {
  return role === 'admin' || role === 'technician';
}
