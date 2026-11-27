import { OG_SIZE, OG_TYPE, ogImage } from '@/lib/ogImage';

export const size = OG_SIZE;
export const contentType = OG_TYPE;
export const alt = 'PHAEMOS: Documentation';

export default function Image() {
  return ogImage('Documentation', 'Setup, architecture, the API and sensor reference and security.');
}
