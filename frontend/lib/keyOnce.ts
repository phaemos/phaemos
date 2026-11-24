// a device key is shown once. POST /devices and POST /devices/{id}/rotate-key are the only answers that carry `api_key`, because the
// server keeps only a keyed hash, so a key that is lost can only be replaced. This is the state of the dialog that shows it: the key
// lives in `shown` and `confirming` and nowhere else and closing the dialog can only be done through a confirmation that drops it;
// no import, so the tests can load it.

export type KeyOnce =
  | { phase: 'closed'; key: null }
  | { phase: 'shown'; key: string; copied: boolean }
  // the person asked to close and is being asked whether they have saved the key
  | { phase: 'confirming'; key: string; copied: boolean };

export type KeyAction = { type: 'show'; key: string } | { type: 'copied' } | { type: 'ask_close' } | { type: 'keep' } | { type: 'close' };

export const CLOSED: KeyOnce = { phase: 'closed', key: null };

export function keyReducer(state: KeyOnce, action: KeyAction): KeyOnce {
  switch (action.type) {
    case 'show':
      return action.key ? { phase: 'shown', key: action.key, copied: false } : CLOSED;
    case 'copied':
      return state.phase === 'closed' ? state : { ...state, copied: true };
    case 'ask_close':
      return state.phase === 'shown' ? { phase: 'confirming', key: state.key, copied: state.copied } : state;
    case 'keep':
      return state.phase === 'confirming' ? { phase: 'shown', key: state.key, copied: state.copied } : state;
    case 'close':
      // only a confirmed close drops the key. A close that was never asked for leaves the dialog as it is.
      return state.phase === 'confirming' ? CLOSED : state;
  }
}

// the sentence under the key. It says what is true: the key cannot be read again and the old key has stopped working when it was a rotation.
export function keyWarning(rotated: boolean): string {
  return rotated
    ? 'This is the only time this key is shown. It cannot be read again. The old key has stopped working, so the node is cut off until this key is in its firmware.'
    : 'This is the only time this key is shown. It cannot be read again. If it is lost, rotate the key to make a new one.';
}

// the new key from an answer or null when the answer carries none. Nothing else of the answer is kept with it.
export function keyFromAnswer(data: unknown): string | null {
  if (!data || typeof data !== 'object') return null;
  const k = (data as { api_key?: unknown }).api_key;
  return typeof k === 'string' && k.length > 0 ? k : null;
}
