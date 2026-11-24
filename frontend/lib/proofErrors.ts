import { errorInfo, proofField } from './apiCode.ts';
import { lockedMessage } from './signInErrors.ts';

// where the answer to a failed action that asks for a proof is shown. It is decided by the error's code (docs/api-conventions.md) and
// the sentence is only what is shown. A wrong or missing proof goes beside its field (both fields when the API does not say which was
// wrong), a 429 goes in the dialog in plain words and anything else is not about the proof and is left to the caller.
export interface ProofSlots {
  password: (text: string) => void;
  code: (text: string) => void;
  dialog: (text: string) => void;
}

export function routeProofError(err: unknown, asks: { password: boolean; code: boolean }, slots: ProofSlots, fallbackText: string): boolean {
  const info = errorInfo(err);
  const locked = lockedMessage(err);
  if (locked) {
    slots.dialog(locked);
    return true;
  }
  const field = proofField(info.code, asks);
  if (!field) return false;
  const shown = info.detail ?? fallbackText;
  if (field === 'both') {
    slots.password(shown);
    slots.code(shown);
  } else if (field === 'password') slots.password(shown);
  else if (field === 'code') slots.code(shown);
  else slots.dialog(shown);
  return true;
}
