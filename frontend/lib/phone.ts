// the phone number format the API accepts (backend/app/schemas/user.py, phone_number_format): empty to clear the
// number, otherwise a plus sign then 8 to 15 digits. Spaces and hyphens are dropped before the check.

export const PHONE_HINT = 'International format with a plus sign, for example +447700900000. Leave it empty for no text alerts.';

export function cleanPhone(value: string): string {
  return value.replace(/[\s-]/g, '');
}

export function phoneProblem(value: string): string | null {
  const cleaned = cleanPhone(value);
  if (cleaned === '' || /^\+[0-9]{8,15}$/.test(cleaned)) return null;
  return 'Use a plus sign then 8 to 15 digits, for example +447700900000.';
}
