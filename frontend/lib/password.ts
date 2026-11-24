// the password rules the API enforces on register, accept-invite and change-password
// (backend/app/schemas/user.py). Keep this in step with that file.

export interface PasswordRule {
  id: 'length' | 'bytes' | 'upper' | 'digit';
  text: string;
  met: boolean;
}

const encoder = new TextEncoder();

export function passwordRules(password: string): PasswordRule[] {
  return [
    { id: 'length', text: 'At least 8 characters', met: password.length >= 8 },
    // bcrypt only reads the first 72 bytes, so the API refuses anything longer
    { id: 'bytes', text: 'At most 72 bytes', met: encoder.encode(password).length <= 72 },
    { id: 'upper', text: 'One capital letter', met: /[A-Z]/.test(password) },
    { id: 'digit', text: 'One number', met: /\d/.test(password) },
  ];
}

export function passwordProblem(password: string): string | null {
  const failed = passwordRules(password).find((r) => !r.met);
  if (!failed) return null;
  return {
    length: 'The password needs at least 8 characters.',
    bytes: 'The password is too long. Use at most 72 bytes.',
    upper: 'The password needs a capital letter.',
    digit: 'The password needs a number.',
  }[failed.id];
}
