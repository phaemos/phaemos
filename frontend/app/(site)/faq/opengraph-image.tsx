import { OG_SIZE, OG_TYPE, ogImage } from '@/lib/ogImage';

export const size = OG_SIZE;
export const contentType = OG_TYPE;
export const alt = 'PHAEMOS: Questions and answers';

export default function Image() {
  return ogImage('Questions and answers', 'Running PHAEMOS, adding machines, alerts, the anomaly model and accounts.');
}
