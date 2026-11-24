import { OG_SIZE, OG_TYPE, ogImage } from '@/lib/ogImage';

export const size = OG_SIZE;
export const contentType = OG_TYPE;
export const alt = 'PHAEMOS: Terms of use';

export default function Image() {
  return ogImage('Terms of use', 'The terms for the PHAEMOS website and the hosted service.');
}
