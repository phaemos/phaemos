// an invitation link carries a one-time token in the address fragment (/accept-invite#token=...), which a browser never sends to a
// server, so it cannot land in a server log. Only the fragment is accepted. The older query form (?token=...) reached the web server
// and its logs, so a link of that kind is treated as dead: `legacyQuery` says it was there, the token is taken out of the address
// and the page tells the person to ask for a new invitation.

export interface InviteRead {
  token: string | null;
  // a token was in the query string, where it is no longer accepted
  legacyQuery: boolean;
  // the address to show once the token is read: the same path and any other query, with no token and no fragment
  cleaned: string;
}

export function readInviteToken(pathname: string, search: string, hash: string): InviteRead {
  const token = (new URLSearchParams(hash.replace(/^#/, '')).get('token') ?? '').trim();
  const query = new URLSearchParams(search.replace(/^\?/, ''));
  const legacyQuery = Boolean((query.get('token') ?? '').trim());
  query.delete('token');
  const rest = query.toString();
  return { token: token || null, legacyQuery, cleaned: rest ? `${pathname}?${rest}` : pathname };
}
