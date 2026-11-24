// the share card for a public page: the emblem and the vector wordmark from components/ui/Wordmark.tsx, then the page's
// own title and one line, on the brand's dark navy. Each route's opengraph-image.tsx calls this, so every page gets its own
// card at build time and they all share one layout. The home page keeps the brand artwork in app/opengraph-image.png.
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { ImageResponse } from 'next/og';
import { WORDMARK_LETTERS, WORDMARK_RATIO, WORDMARK_TRIANGLE, WORDMARK_VIEWBOX } from '@/components/ui/Wordmark';

export const OG_SIZE = { width: 1200, height: 630 };
export const OG_TYPE = 'image/png';

// the brand board's colours. This file draws a picture, not the interface, so it holds them here rather than as tokens.
const NAVY = '#0B1220';
const OFF_WHITE = '#F8FAFC';
const LIGHT_GREY = '#CBD5E1';
const ACCENT = '#3B82F6';
const RULE = '#1E293B';


export async function ogImage(title: string, line?: string): Promise<ImageResponse> {
  // each path is written out in full so the build traces these three files and nothing else
  const [emblem, exo, manrope] = await Promise.all([
    readFile(join(process.cwd(), 'public/brand/phaemos-emblem-dark.png')),
    readFile(join(process.cwd(), 'assets/fonts/Exo2-SemiBold.ttf')),
    readFile(join(process.cwd(), 'assets/fonts/Manrope-Medium.ttf')),
  ]);
  const emblemSrc = `data:image/png;base64,${emblem.toString('base64')}`;
  const markHeight = 40;

  return new ImageResponse(
    (
      <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', background: NAVY, padding: '72px 80px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 28 }}>
          {/* eslint-disable-next-line @next/next/no-img-element -- the image renderer takes plain img elements only */}
          <img src={emblemSrc} width={76} height={76} alt="" />
          <svg viewBox={WORDMARK_VIEWBOX} width={markHeight * WORDMARK_RATIO} height={markHeight}>
            <path fill={OFF_WHITE} fillRule="evenodd" d={WORDMARK_LETTERS} />
            <path fill={ACCENT} d={WORDMARK_TRIANGLE} />
          </svg>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24, borderTop: `2px solid ${RULE}`, paddingTop: 40 }}>
          <div style={{ fontFamily: 'Exo 2', fontSize: title.length > 48 ? 56 : 68, lineHeight: 1.1, color: OFF_WHITE, letterSpacing: '-0.01em' }}>{title}</div>
          {line ? <div style={{ fontFamily: 'Manrope', fontSize: 30, lineHeight: 1.4, color: LIGHT_GREY, maxWidth: 980 }}>{line}</div> : null}
        </div>
      </div>
    ),
    {
      ...OG_SIZE,
      fonts: [
        { name: 'Exo 2', data: exo, weight: 600, style: 'normal' },
        { name: 'Manrope', data: manrope, weight: 500, style: 'normal' },
      ],
    },
  );
}
