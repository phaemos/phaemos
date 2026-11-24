import { OG_SIZE, OG_TYPE, ogImage } from '@/lib/ogImage';

export const size = OG_SIZE;
export const contentType = OG_TYPE;
export const alt = 'PHAEMOS: Cookies and browser storage';

export default function Image() {
  return ogImage('Cookies and browser storage', 'Every cookie and storage key the website, dashboard and API use.');
}
