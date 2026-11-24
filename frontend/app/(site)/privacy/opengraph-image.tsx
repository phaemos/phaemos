import { OG_SIZE, OG_TYPE, ogImage } from '@/lib/ogImage';

export const size = OG_SIZE;
export const contentType = OG_TYPE;
export const alt = 'PHAEMOS: Privacy notice';

export default function Image() {
  return ogImage('Privacy notice', 'What personal data PHAEMOS collects, why, who receives it and your rights.');
}
