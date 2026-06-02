import type { MetadataRoute } from 'next';

const BASE_URL = 'https://phaemos.io';

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: BASE_URL,               lastModified: new Date(), changeFrequency: 'monthly', priority: 1 },
    { url: `${BASE_URL}/devices`,  lastModified: new Date(), changeFrequency: 'daily',   priority: 0.8 },
    { url: `${BASE_URL}/alerts`,   lastModified: new Date(), changeFrequency: 'daily',   priority: 0.7 },
    { url: `${BASE_URL}/tickets`,  lastModified: new Date(), changeFrequency: 'daily',   priority: 0.7 },
    { url: `${BASE_URL}/compare`,  lastModified: new Date(), changeFrequency: 'weekly',  priority: 0.5 },
  ];
}
