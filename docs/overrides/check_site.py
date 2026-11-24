#!/usr/bin/env python3
"""Checks the built documentation site in Chromium and writes a report.

Run it after `mkdocs build -d <site>`; docs/README.md has the exact commands. It serves the built folder on a local port above
24000 and makes no request to any other origin. It reports, in both themes:

  contrast of every text style, text under 13 px, target sizes, focus rings on every tab stop of four pages,
  sideways scroll at 320, 390, 768 and 1440 px wide at 100 and 200 per cent text, requests to other origins,
  hover and search states, the architecture diagrams, reduced motion, reading with scripts off and the theme switch.

It also saves screenshots. The exit code is 1 when any check fails.
"""
import argparse
import functools
import glob
import http.server
import json
import os
import re
import threading

from playwright.sync_api import sync_playwright

PORT = 26731
PAGES = {  # name: path. The four screenshot pages come first
    "home": "index.html",
    "long-reference": "api-reference/index.html",
    "wide-tables": "sensor_reference/index.html",
    "code": "development/index.html",
    "architecture": "architecture/index.html",
    "security": "security/index.html",
}
CORE = ["home", "long-reference", "wide-tables", "code"]  # the pages that are screenshotted

WIDTHS = [320, 390, 768, 1440]
SHOT_WIDTHS = [390, 768, 1440]
THEMES = ["light", "dark"]

# runs in the page. Returns one row per text style with its measured contrast
JS_CONTRAST = r"""
(root) => {
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => { cx.clearRect(0,0,1,1); cx.fillStyle = '#000'; cx.fillStyle = c; cx.fillRect(0,0,1,1);
    const d = cx.getImageData(0,0,1,1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const over = (f, b) => [0,1,2].map(i => f[i] * f[3] + b[i] * (1 - f[3]));
  const lum = (c) => { const v = c.map(x => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
  const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); return (Math.max(l1,l2) + 0.05) / (Math.min(l1,l2) + 0.05); };
  const bgOf = (el) => {
    let layers = [], img = false;
    for (let e = el; e; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (s.backgroundImage !== 'none') img = true;
      const c = rgba(s.backgroundColor);
      if (c[3] > 0) layers.push(c);
      if (c[3] >= 1) break;
    }
    let base = [255,255,255,1];
    for (let i = layers.length - 1; i >= 0; i--) { const l = layers[i]; base = [...over(l, base), 1]; }
    return { rgb: base, img };
  };
  const rows = new Map();
  const w = document.createTreeWalker(root || document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    if (!n.nodeValue.trim()) continue;
    const el = n.parentElement;
    if (!el || el.closest('script,style,noscript,template')) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none') continue;
    let op = 1, hidden = false;
    for (let e = el; e; e = e.parentElement) { const st = getComputedStyle(e); op *= parseFloat(st.opacity);
      if (st.display === 'none' || st.visibility === 'hidden') hidden = true; }
    if (hidden || op < 0.05) continue;
    if (r.right < 0 || r.left > document.documentElement.scrollWidth) continue;
    const fgc = rgba(s.color); fgc[3] *= op;
    const bg = bgOf(el);
    const fg = over(fgc, bg.rgb);
    const cr = ratio(fg, bg.rgb);
    const size = parseFloat(s.fontSize), weight = s.fontWeight;
    const key = fg.map(Math.round).join(',') + '|' + bg.rgb.map(Math.round).join(',') + '|' + size + '|' + weight;
    const tag = el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.split(/\s+/)[0] : '');
    const row = rows.get(key) || { fg: fg.map(Math.round), bg: bg.rgb.map(Math.round), ratio: cr, size, weight, count: 0, example: tag, text: n.nodeValue.trim().slice(0, 40), image: bg.img };
    row.count++; rows.set(key, row);
  }
  if (rows.size === 0 && root) {
    // an icon with no text: its colour against what it sits on
    const bg = bgOf(root); const fgc = rgba(getComputedStyle(root).color); const fg = over(fgc, bg.rgb);
    rows.set('icon', { fg: fg.map(Math.round), bg: bg.rgb.map(Math.round), ratio: ratio(fg, bg.rgb), size: 0, weight: '', count: 1, example: 'icon', text: '', image: bg.img });
  }
  return [...rows.values()];
}
"""

# runs in the page. Returns the interactive elements that are visible, with their box
JS_TARGETS = r"""
() => {
  const sel = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [tabindex]:not([tabindex="-1"]), label.md-header__button, label.md-nav__link, .tabbed-labels > label';
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width <= 1 || r.height <= 1) continue;
    let hidden = false;
    for (let e = el; e; e = e.parentElement) { const s = getComputedStyle(e);
      if (s.display === 'none' || s.visibility === 'hidden' || (parseFloat(s.opacity) < 0.05 && !el.classList.contains('headerlink')) || s.pointerEvents === 'none') hidden = true; }
    if (hidden) continue;
    const st = getComputedStyle(el);
    if (st.position === 'absolute' && st.clip !== 'auto') continue;
    // a link inside a line of text is exempt from a minimum size (WCAG 2.5.8 and 2.5.5 inline exception)
    let inline = false;
    if (el.tagName === 'A' && st.display === 'inline') {
      const p = el.parentElement;
      inline = !!p && p.textContent.trim().length > el.textContent.trim().length;
    }
    // the copy of a table's scroll box is a region, not a control the reader aims at
    out.push({ tag: el.tagName.toLowerCase(), cls: (typeof el.className === 'string' ? el.className : '').split(/\s+/)[0],
      text: (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 30), w: r.width, h: r.height, inline });
  }
  return out;
}
"""

JS_SVG = r"""
() => {
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => { cx.clearRect(0,0,1,1); cx.fillStyle = '#000'; cx.fillStyle = c; cx.fillRect(0,0,1,1);
    const d = cx.getImageData(0,0,1,1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const lum = (c) => { const v = c.map(x => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
  const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); return (Math.max(l1,l2) + 0.05) / (Math.min(l1,l2) + 0.05); };
  const out = { foreign: document.querySelectorAll('.ph-diagram foreignObject').length, unnamed: 0, nosummary: 0, overfit: 0, diagrams: 0, ready: 0, textMin: 99, lineMin: 99, texts: 0, lines: 0, smallest: 99, worstText: '' };
  for (const box of document.querySelectorAll('.ph-diagram')) {
    out.diagrams++;
    if (!box.dataset.ready) continue;
    out.ready++;
    const pic = box.querySelector('[role=img]');
    if (!pic || !(pic.getAttribute('aria-label') || '').trim()) out.unnamed++;
    const fig = box.closest('figure');
    const sum = fig && fig.querySelector('figcaption');
    if (!sum || sum.textContent.trim().length < 60) out.nosummary++;
    if (!fig || !(fig.getAttribute('aria-label') || '').trim()) out.unnamed++;
    const sv = box.querySelector('svg');
    if (sv && !box.classList.contains('is-full') && sv.getBoundingClientRect().right > box.getBoundingClientRect().right + 1) out.overfit++;
    const page = rgba(getComputedStyle(box).backgroundColor);
    for (const t of box.querySelectorAll('svg text, svg tspan')) {
      if (!t.textContent.trim() || t.tagName === 'text' && t.querySelector('tspan')) continue;
      const r = t.getBoundingClientRect(); if (r.width < 1) continue;
      const fg = rgba(getComputedStyle(t).fill);
      let bg = page;
      for (const e of document.elementsFromPoint(r.left + r.width / 2, r.top + r.height / 2)) {
        if (e.closest('svg') && /^(rect|path|polygon|ellipse|circle)$/.test(e.tagName.toLowerCase())) {
          const f = rgba(getComputedStyle(e).fill); if (f[3] > 0.5) { bg = f; break; } }
      }
      const cr = ratio(fg, bg); out.texts++;
      const sv0 = box.querySelector('svg'); const nat = parseFloat(sv0.getAttribute('data-natural-width')) || sv0.getBoundingClientRect().width;
      out.smallest = Math.min(out.smallest, parseFloat(getComputedStyle(t).fontSize) * (sv0.getBoundingClientRect().width / nat));
      if (cr < out.textMin) { out.textMin = cr; out.worstText = t.textContent.trim().slice(0, 30); }
    }
    for (const e of box.querySelectorAll('svg path, svg line, svg polyline')) {
      const s = getComputedStyle(e); const sw = parseFloat(s.strokeWidth);
      if (s.stroke === 'none' || !(sw > 0.5)) continue;
      const cr = ratio(rgba(s.stroke), page); out.lines++; out.lineMin = Math.min(out.lineMin, cr);
    }
  }
  return out;
}
"""

JS_FOCUS = r"""
() => {
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => { cx.clearRect(0,0,1,1); cx.fillStyle = '#000'; cx.fillStyle = c; cx.fillRect(0,0,1,1);
    const d = cx.getImageData(0,0,1,1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const over = (f, b) => [0,1,2].map(i => f[i] * f[3] + b[i] * (1 - f[3]));
  const lum = (c) => { const v = c.map(x => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
  const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); return (Math.max(l1,l2) + 0.05) / (Math.min(l1,l2) + 0.05); };
  const el = document.activeElement;
  if (!el || el === document.body) return null;
  const s = getComputedStyle(el);
  let layers = [];
  for (let e = el.parentElement; e; e = e.parentElement) { const c = rgba(getComputedStyle(e).backgroundColor);
    if (c[3] > 0) layers.push(c); if (c[3] >= 1) break; }
  let base = [255,255,255,1];
  for (let i = layers.length - 1; i >= 0; i--) base = [...over(layers[i], base), 1];
  const ow = parseFloat(s.outlineWidth) || 0;
  const ringOk = s.outlineStyle !== 'none' && ow >= 3;
  const col = rgba(s.outlineColor);
  const cr = ratio(over(col, base), base);
  const r = el.getBoundingClientRect();
  const off = (parseFloat(s.outlineOffset) || 0) + ow;
  let clipped = false;
  for (let p = el.parentElement; p && p !== document.documentElement; p = p.parentElement) {
    const ps = getComputedStyle(p);
    if (/(hidden|clip)/.test(ps.overflowX + ps.overflowY)) {
      const pr = p.getBoundingClientRect();
      if (r.left - off < pr.left - 0.5 || r.right + off > pr.right + 0.5 || r.top - off < pr.top - 0.5 || r.bottom + off > pr.bottom + 0.5) { clipped = true; }
    }
  }
  return { tag: el.tagName.toLowerCase(), cls: (typeof el.className === 'string' ? el.className : '').split(/\s+/)[0],
    text: (el.getAttribute('aria-label') || el.textContent || el.getAttribute('href') || '').trim().slice(0, 40),
    width: ow, style: s.outlineStyle, ratio: cr, ringOk, clipped, visible: r.width > 0 && r.height > 0,
    shown: (() => { let o = 1; for (let e = el; e; e = e.parentElement) { const st = getComputedStyle(e); o *= parseFloat(st.opacity); if (st.visibility === 'hidden') return false; } return o > 0.05; })(),
    box: [Math.round(r.top), Math.round(r.bottom), Math.round(r.left), Math.round(r.right), Math.round(scrollY), innerHeight],
    inView: r.right > 0 && r.bottom > 0 && r.left < innerWidth && r.top < innerHeight && r.width > 0 && r.height > 0 };
}
"""

JS_OVERFLOW = r"""
() => {
  const de = document.documentElement;
  const over = de.scrollWidth - de.clientWidth;
  const offenders = [];
  if (over > 0) {
    for (const el of document.querySelectorAll('body *')) {
      const r = el.getBoundingClientRect();
      if (r.right > de.clientWidth + 1 && r.width > 0) {
        let scroller = false;
        for (let p = el.parentElement; p; p = p.parentElement) { const s = getComputedStyle(p);
          if (/(auto|scroll|hidden|clip)/.test(s.overflowX) && p !== de && p !== document.body) { scroller = true; break; } }
        if (!scroller) offenders.push(el.tagName.toLowerCase() + '.' + (typeof el.className === 'string' ? el.className.split(/\s+/)[0] : '') + ' right=' + Math.round(r.right));
      }
      if (offenders.length > 4) break;
    }
  }
  return { over, offenders };
}
"""

JS_MOTION = r"""
() => {
  const parse = (v) => Math.max(0, ...v.split(',').map(x => { x = x.trim(); return x.endsWith('ms') ? parseFloat(x) : parseFloat(x) * 1000; }).filter(x => !isNaN(x)));
  let worst = 0, example = '', smooth = getComputedStyle(document.documentElement).scrollBehavior;
  for (const el of document.querySelectorAll('*')) {
    const s = getComputedStyle(el);
    const d = Math.max(parse(s.transitionDuration), parse(s.animationDuration));
    if (d > worst) { worst = d; example = el.tagName.toLowerCase() + '.' + (typeof el.className === 'string' ? el.className.split(/\s+/)[0] : ''); }
    if (s.scrollBehavior === 'smooth') smooth = 'smooth';
  }
  return { worst, example, smooth, matches: matchMedia('(prefers-reduced-motion: reduce)').matches };
}
"""


def settle(pg):
    pg.wait_for_load_state("networkidle")
    if pg.locator(".ph-diagram").count():
        try:
            pg.wait_for_selector(".ph-diagram[data-ready]", timeout=30000)
            pg.wait_for_timeout(400)
        except Exception:
            pass


def search_for(pg, term):
    """Types into the search box. The theme ignores a query that arrives before its index is ready, so a second try is made."""
    pg.wait_for_timeout(1200)
    for _ in range(3):
        pg.fill("input.md-search__input", "")
        pg.keyboard.type(term, delay=40)
        try:
            pg.wait_for_selector(".md-search-result__item", timeout=3000)
            return
        except Exception:
            pg.wait_for_timeout(1000)


def serve(site):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k):
            pass

    handler = functools.partial(Quiet, directory=site)
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def find_chromium():
    env = os.environ.get("CHROMIUM_PATH")
    if env:
        return env
    hits = glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"))
    hits += glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome"))
    return sorted(hits)[-1] if hits else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True, help="the built site folder")
    ap.add_argument("--out", required=True, help="where the report and the screenshots go")
    ap.add_argument("--allow-placeholders", action="store_true", help="do not fail on an unfilled {{NAME}} in the built pages (a scratch build only)")
    ap.add_argument("--only", default="", help="run only the checks whose title holds this text")
    ap.add_argument("--no-shots", action="store_true", help="skip the screenshots")
    args = ap.parse_args()
    os.makedirs(os.path.join(args.out, "screenshots"), exist_ok=True)
    srv = serve(args.site)
    base = f"http://127.0.0.1:{PORT}/"
    all_pages = sorted(os.path.relpath(p, args.site) for p in glob.glob(os.path.join(args.site, "**/index.html"), recursive=True))
    lines, failures = [], []
    foreign = set()

    def fail(msg):
        failures.append(msg)
        lines.append(f"FAIL {msg}")

    with sync_playwright() as pw:
        exe = find_chromium()
        browser = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()

        def new_context(theme, width=1440, **kw):
            ctx = browser.new_context(viewport={"width": width, "height": 900}, color_scheme=theme, **kw)
            ctx.set_default_timeout(15000)
            ctx.add_init_script("document.addEventListener('securitypolicyviolation', e => { (window.__csp = window.__csp || []).push(e.violatedDirective + ' ' + e.blockedURI); });")
            ctx.on("request", lambda r: foreign.add(r.url) if not (r.url.startswith(base) or r.url.startswith("data:") or r.url.startswith("blob:")) else None)
            return ctx

        def load(pg, path, tries=3):
            """Opens a page and waits for it. A busy machine gets more than one try."""
            last = None
            for _ in range(tries):
                try:
                    pg.goto(base + path, timeout=30000)
                    settle(pg)
                    viol = pg.evaluate("window.__csp || []")
                    if viol:
                        fail(f"content security policy violations on {path}: {viol[:3]}")
                    return
                except Exception as e:  # noqa: BLE001
                    last = e
                    pg.wait_for_timeout(500)
            raise last

        def section(title, fn):
            """A check that cannot run is a finding, never a crash that loses the report."""
            if args.only and args.only.lower() not in title.lower():
                return
            lines.append(f"## {title}\n")
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                fail(f"the check '{title}' could not finish: {type(e).__name__}: {str(e).splitlines()[0][:160] if str(e) else ''}")
            lines.append("")

        def safely(label, fn, default=None):
            try:
                return fn()
            except Exception as e:  # noqa: BLE001
                fail(f"could not measure {label}: {type(e).__name__}: {str(e).splitlines()[0][:120] if str(e) else ''}")
                return default

        # ------------------------------------------------------------------------------------------------ contrast
        def contrast():
            lines.append("| Theme | Page | Styles | Lowest ratio | Lowest style (text on background, size) | Under 4.5 | Under 7 |")
            lines.append("| --- | --- | --- | --- | --- | --- | --- |")
            image_notes, small = {}, []
            for theme in THEMES:
                ctx = new_context(theme)
                for name, path in PAGES.items():
                    def one():
                        pg = ctx.new_page()
                        try:
                            load(pg, path)
                            rows = pg.evaluate(JS_CONTRAST)
                        finally:
                            pg.close()
                        low = min(rows, key=lambda r: r["ratio"])
                        u45 = [r for r in rows if r["ratio"] < 4.5]
                        u7 = [r for r in rows if r["ratio"] < 7]
                        fg = "rgb(" + ",".join(map(str, low["fg"])) + ")"
                        bgc = "rgb(" + ",".join(map(str, low["bg"])) + ")"
                        lines.append(f"| {theme} | {name} | {len(rows)} | {low['ratio']:.2f} | {fg} on {bgc}, {low['size']:.0f}px, {low['example']} | {len(u45)} | {len(u7)} |")
                        for r in u45:
                            fail(f"contrast {r['ratio']:.2f} in {theme} on {name}: {r['example']} '{r['text']}' {r['fg']} on {r['bg']}")
                        for r in rows:
                            if r["image"]:
                                image_notes[name] = True
                            if r["size"] < 13:
                                small.append((theme, name, r["size"], r["example"], r["text"]))
                    safely(f"contrast on {name} ({theme})", one)
                ctx.close()
            if image_notes:
                lines.append("\nText sits over the soft scroll edge of a table box on: " + ", ".join(image_notes) + ". The measure uses the colour under it.")
            for t in small:
                fail(f"text under 13px: {t}")
            if not small:
                lines.append("\nNo text under 13 px on any page in either theme.")

        section("Contrast of every text style", contrast)

        # --------------------------------------------------------------------- scripts off with a dark system theme
        def nojs_dark():
            # scripts are blocked and the page's own <noscript> style is applied, which is what a reader with scripts off gets
            ctx = new_context("dark")
            ctx.route("**/*.js", lambda r: r.abort())
            lines.append("| Page | Styles | Lowest ratio | Under 4.5 |")
            lines.append("| --- | --- | --- | --- |")
            for name in ("home", "code", "long-reference"):
                def one():
                    pg = ctx.new_page()
                    try:
                        pg.goto(base + PAGES[name], timeout=30000)
                        pg.wait_for_load_state("networkidle")
                        css = pg.evaluate("[...document.querySelectorAll('noscript')].map(n => n.textContent).join('\\n')")
                        pg.add_style_tag(content=re.sub(r"</?style>", "", css))
                        pg.wait_for_timeout(700)  # the theme fades colours over a quarter of a second
                        rows = pg.evaluate(JS_CONTRAST)
                    finally:
                        pg.close()
                    low = min(r["ratio"] for r in rows)
                    bad = [r for r in rows if r["ratio"] < 4.5]
                    lines.append(f"| {name} | {len(rows)} | {low:.2f} | {len(bad)} |")
                    if bad:
                        fail(f"scripts off and a dark system theme: {len(bad)} text styles under 4.5:1 on {name} (lowest {low:.2f})")
                safely(f"scripts-off dark contrast on {name}", one)
            ctx.close()

        section("Scripts off with a dark system theme (contrast)", nojs_dark)

        # --------------------------------------------------------------------------------------------- target sizes
        def targets():
            lines.append("| Page | Width | Targets checked | Under 44 px |")
            lines.append("| --- | --- | --- | --- |")
            for width in (390, 768, 1440):
                ctx = new_context("light", width)
                for name, path in PAGES.items():
                    def one():
                        pg = ctx.new_page()
                        try:
                            load(pg, path)
                            pg.evaluate("window.scrollTo(0, 1500)")
                            pg.evaluate("window.scrollTo(0, 1200)")
                            pg.wait_for_timeout(300)
                            items = pg.evaluate(JS_TARGETS)
                        finally:
                            pg.close()
                        checked = [i for i in items if not i["inline"]]
                        small = [i for i in checked if i["w"] < 43.9 or i["h"] < 43.9]
                        lines.append(f"| {name} | {width} | {len(checked)} | {len(small)} |")
                        for i in small[:12]:
                            fail(f"target {i['w']:.0f}x{i['h']:.0f} on {name} at {width}: {i['tag']}.{i['cls']} '{i['text']}'")
                    safely(f"targets on {name} at {width}", one)
                ctx.close()

        section("Target sizes (44 by 44 px, inline links in running text exempt)", targets)

        # ----------------------------------------------------------------------------------------------- focus rings
        def focus():
            lines.append("| Theme | Width | Page | Tab stops | No 3 px ring | Ring under 3:1 | Ring clipped | Off screen | Heading links in order |")
            lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
            plan = [("light", 1440, list(PAGES)), ("dark", 1440, CORE), ("light", 390, CORE + ["architecture"]), ("light", 768, CORE)]
            for theme, width, names in plan:
                ctx = new_context(theme, width)
                for name in names:
                    def one():
                        pg = ctx.new_page()
                        try:
                            load(pg, PAGES[name])
                            bad_ring, bad_contrast, clipped, off, hl, stops, labels = [], [], [], [], 0, 0, []
                            for _ in range(900):
                                pg.keyboard.press("Tab")
                                pg.wait_for_timeout(40)
                                info = pg.evaluate(JS_FOCUS)
                                if info is None:
                                    break
                                if info["clipped"] or not info["inView"] or (not info["shown"] and info["cls"] != "md-search__input"):
                                    # a drawer or panel may still be sliding in: look again once it has settled
                                    for _wait in range(3):
                                        pg.wait_for_timeout(400)
                                        info = pg.evaluate(JS_FOCUS) or info
                                        if info["inView"] and info["shown"] and not info["clipped"]:
                                            break
                                stops += 1
                                labels.append(info["text"])
                                if stops == 1 and info["cls"] != "md-skip":
                                    fail(f"first tab stop on {name} is not the skip link: {info}")
                                if not info["ringOk"]:
                                    bad_ring.append(info)
                                if info["ratio"] < 3:
                                    bad_contrast.append(info)
                                if info["clipped"]:
                                    clipped.append(info)
                                if not info["inView"]:
                                    off.append(info)
                                if not info["shown"] and info["cls"] != "md-search__input":
                                    fail(f"keyboard focus is on something nobody can see on {name} ({theme}, {width}): {info['tag']}.{info['cls']} '{info['text']}'")
                                if info["cls"] == "headerlink":
                                    hl += 1
                        finally:
                            pg.close()
                        lines.append(f"| {theme} | {width} | {name} | {stops} | {len(bad_ring)} | {len(bad_contrast)} | {len(clipped)} | {len(off)} | {hl} |")
                        for i in bad_ring[:5]:
                            fail(f"focus ring under 3 px on {name} ({theme}, {width}): {i['tag']}.{i['cls']} '{i['text']}' width={i['width']} style={i['style']}")
                        for i in bad_contrast[:5]:
                            fail(f"focus ring contrast {i['ratio']:.2f} on {name} ({theme}, {width}): {i['tag']}.{i['cls']} '{i['text']}'")
                        for i in clipped[:5]:
                            fail(f"focus ring clipped on {name} ({theme}, {width}): {i['tag']}.{i['cls']} '{i['text']}'")
                        for i in off[:5]:
                            fail(f"focus is outside the screen on {name} ({theme}, {width}): {i['tag']}.{i['cls']} '{i['text']}' box {i['box']} ({len(off)} stops)")
                        if hl:
                            fail(f"{hl} heading links are tab stops on {name}")
                        if width < 1220 and not any("Navigation menu" in t for t in labels):
                            fail(f"the menu button cannot be reached by keyboard on {name} at {width}")
                    safely(f"focus on {name} ({theme}, {width})", one)
                ctx.close()

        section("Focus rings and focus order on every tab stop", focus)

        # ----------------------------------------------------------------------------- the drawer, by keyboard
        def drawer():
            for width in (390, 768):
                ctx = new_context("light", width)
                pg = ctx.new_page()
                load(pg, PAGES["home"])
                for _ in range(8):
                    pg.keyboard.press("Tab")
                    if "Navigation menu" in (pg.evaluate("document.activeElement.getAttribute('aria-label') || ''")):
                        break
                else:
                    fail(f"the menu button never took focus at {width}")
                    ctx.close()
                    continue
                pg.keyboard.press("Enter")
                pg.wait_for_timeout(500)
                opened = pg.evaluate("document.getElementById('__drawer').checked")
                inside = pg.evaluate("!!document.activeElement.closest('.md-sidebar--primary')")
                expanded = pg.evaluate("document.querySelector('label.md-header__button[for=__drawer]').getAttribute('aria-expanded')")
                pg.keyboard.press("Escape")
                pg.wait_for_timeout(500)
                closed = not pg.evaluate("document.getElementById('__drawer').checked")
                back = pg.evaluate("(document.activeElement.getAttribute('aria-label') || '').includes('Navigation menu')")
                lines.append(f"- {width}: opens {opened}, expanded {expanded}, focus moves inside {inside}, Escape closes {closed}, focus returns to the button {back}")
                if not (opened and inside and closed and back and expanded == "true"):
                    fail(f"the drawer does not behave as a keyboard control at {width}")
                ctx.close()

        section("The menu drawer by keyboard", drawer)

        # ---------------------------------------------------------------------------------- wide tables, any width
        def tables():
            lines.append("| Page | Width | Tables | Overflowing | Overflowing with hint and region and name | Fitting but still a stop |")
            lines.append("| --- | --- | --- | --- | --- | --- |")
            js = r"""() => [...document.querySelectorAll('.ph-table-scroll')].map(b => {
              const h = b.previousElementSibling; const hidden = !h || getComputedStyle(h).display === 'none';
              return { over: b.scrollWidth > b.clientWidth + 1, hint: !hidden, role: b.getAttribute('role'), tab: b.getAttribute('tabindex'),
                       label: b.getAttribute('aria-label') || '', heading: b.getAttribute('data-heading') || '' } })"""
            for width in (768, 1024, 1440):
                ctx = new_context("light", width)
                for name in ("wide-tables", "long-reference", "architecture"):
                    def one():
                        pg = ctx.new_page()
                        try:
                            load(pg, PAGES[name])
                            rows = pg.evaluate(js)
                        finally:
                            pg.close()
                        over = [r for r in rows if r["over"]]
                        good = [r for r in over if r["hint"] and r["role"] == "region" and r["tab"] == "0" and r["heading"] and r["heading"] in r["label"]]
                        stops = [r for r in rows if not r["over"] and (r["tab"] is not None or r["hint"])]
                        lines.append(f"| {name} | {width} | {len(rows)} | {len(over)} | {len(good)} | {len(stops)} |")
                        if len(good) != len(over):
                            fail(f"{len(over) - len(good)} overflowing tables on {name} at {width} lack a hint or a region or a name from their heading")
                        if stops:
                            fail(f"{len(stops)} tables that fit still carry a tab stop or a hint on {name} at {width}")
                    safely(f"tables on {name} at {width}", one)
                ctx.close()

        section("Wide tables: the cue, the name and the tab stop at any width", tables)

        # ------------------------------------------------------------------------------------------ sideways scroll
        def sideways():
            lines.append("| Width | Text size | Pages checked | Pages that scroll sideways |")
            lines.append("| --- | --- | --- | --- |")
            for width in WIDTHS:
                for zoom in (100, 200):
                    ctx = new_context("light", width)
                    pg = ctx.new_page()
                    bad = []
                    for path in all_pages:
                        def one():
                            pg.goto(base + path, timeout=30000)
                            pg.wait_for_load_state("load")
                            if pg.locator(".ph-diagram").count():
                                settle(pg)
                            if zoom == 200:
                                pg.add_style_tag(content="html{font-size:250% !important}")
                            res = pg.evaluate(JS_OVERFLOW)
                            if res["over"] > 0:
                                bad.append((path, res))
                        safely(f"sideways scroll on {path} at {width}", one)
                    lines.append(f"| {width} | {zoom}% | {len(all_pages)} | {len(bad)} |")
                    for path, res in bad[:6]:
                        fail(f"sideways scroll {res['over']}px at {width} and {zoom}% on {path}: {res['offenders']}")
                    ctx.close()

        section("Sideways scroll (every built page)", sideways)

        # ----------------------------------------------------------------------------------------- reduced motion
        def motion():
            init = """
              window.__smooth = [];
              const wrap = (obj, name) => { const f = obj[name]; if (!f) return; obj[name] = function (...a) {
                const o = a[0]; if (o && typeof o === 'object' && o.behavior === 'smooth') window.__smooth.push(name); return f.apply(this, a); }; };
              wrap(Element.prototype, 'scrollTo'); wrap(Element.prototype, 'scroll'); wrap(Element.prototype, 'scrollIntoView');
              wrap(window, 'scrollTo'); wrap(window, 'scroll'); wrap(Element.prototype, 'scrollBy'); wrap(window, 'scrollBy');
            """
            ctx = new_context("light", reduced_motion="reduce")
            ctx.add_init_script(init)
            pg = ctx.new_page()
            for name in CORE + ["architecture"]:
                def one():
                    load(pg, PAGES[name])
                    m = pg.evaluate(JS_MOTION)
                    # the reader scrolls, opens the search and follows a contents link: the theme's script must not smooth-scroll
                    pg.evaluate("window.scrollTo(0, 1800)")
                    link = pg.locator(".md-sidebar--secondary a.md-nav__link:visible").nth(2)
                    if link.count():
                        link.click()
                    pg.wait_for_timeout(500)
                    pg.keyboard.press("Tab")
                    smooth = pg.evaluate("window.__smooth")
                    ok = m["matches"] and m["worst"] <= 1 and m["smooth"] != "smooth" and not smooth
                    lines.append(f"- {name}: media query {m['matches']}, longest transition or animation {m['worst']:.3f} ms, scroll behaviour {m['smooth']}, smooth scroll requested by script {len(smooth)}")
                    if not ok:
                        fail(f"reduced motion not honoured on {name}: {m} script smooth calls {smooth}")
                safely(f"reduced motion on {name}", one)
            ctx.close()

        section("Reduced motion (styles and script)", motion)

        # --------------------------------------------------------------------------------------------- scripts off
        def noscript():
            ctx = new_context("light", java_script_enabled=False)
            pg = ctx.new_page()
            pg.goto(base + "index.html")
            h1 = pg.inner_text("h1")
            nav_links = pg.locator(".md-nav--primary a.md-nav__link").count()
            toc_links = pg.locator(".md-nav--secondary a").count()
            pg.keyboard.press("Tab")
            first = pg.evaluate("document.activeElement.className")
            lines.append(f"- home heading '{h1}', {nav_links} navigation links and {toc_links} contents links in the page, first tab stop class '{first}'")
            if not h1 or nav_links < 10 or "md-skip" not in first:
                fail("reading with scripts off is incomplete")
            pg.goto(base + PAGES["architecture"])
            src = pg.locator(".ph-diagram").evaluate_all("els => els.map(e => e.textContent.trim().slice(0, 12))")
            summ = pg.locator(".ph-diagram__summary").count()
            lines.append(f"- the architecture page holds {len(src)} diagrams as text (first words {src}) and {summ} written summaries")
            if len(src) != 4 or not all(src) or summ != 4:
                fail("diagrams are not readable as text with a summary when scripts are off")
            ctx.close()
            ctx = new_context("light", 390, java_script_enabled=False)
            pg = ctx.new_page()
            pg.goto(base + "sensor_reference/index.html")
            wide = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            lines.append(f"- a page with wide tables at 390: sideways overflow {wide}px")
            if wide > 0:
                fail("a wide table pushes the page sideways with scripts off")
            ctx.close()

        section("Scripts off", noscript)

        # --------------------------------------------------------------------------- the diagrams, fitted and whole
        def diagrams():
            lines.append("| Theme | Width | Drawn | HTML labels | Unnamed | No summary | Wider than box | Label text lowest | Lines lowest | Smallest label |")
            lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
            for theme in THEMES:
                for width in (390, 1440):
                    def one():
                        ctx = new_context(theme, width)
                        pg = ctx.new_page()
                        try:
                            load(pg, PAGES["architecture"])
                            d = pg.evaluate(JS_SVG)
                            if theme == "light":
                                btn = pg.locator(".ph-diagram__zoom").first
                                name0 = btn.get_attribute("aria-label")
                                p0 = btn.get_attribute("aria-pressed")
                                w0 = pg.evaluate("document.querySelector('.ph-diagram svg').getBoundingClientRect().width")
                                btn.click()
                                p1 = btn.get_attribute("aria-pressed")
                                w1 = pg.evaluate("document.querySelector('.ph-diagram svg').getBoundingClientRect().width")
                                name1 = btn.get_attribute("aria-label")
                                lines.append(f"- {width}: first diagram starts {'full size' if p0 == 'true' else 'fitted'} ({w0:.0f} px), toggles to {w1:.0f} px, button name '{name0}' then '{name1}', pressed {p0} then {p1}")
                                if not (p0 != p1 and w0 != w1 and name0 == name1 == "View at full size"):
                                    fail(f"the full-size control does not toggle with a fixed name at {width}")
                        finally:
                            ctx.close()
                        lines.append(f"| {theme} | {width} | {d['ready']} of {d['diagrams']} | {d['foreign']} | {d['unnamed']} | {d['nosummary']} | {d['overfit']} | {d['textMin']:.2f} | {d['lineMin']:.2f} | {d['smallest']:.0f}px |")
                        if d["diagrams"] == 0 or d["ready"] != d["diagrams"]:
                            fail(f"diagrams not all drawn in {theme} at {width}: {d}")
                        if d["foreign"]:
                            fail(f"{d['foreign']} diagram labels are HTML (a label could load an image from another site)")
                        if d["unnamed"] or d["nosummary"]:
                            fail(f"diagrams without a name or a summary in {theme} at {width}: {d}")
                        if d["overfit"]:
                            fail(f"{d['overfit']} diagrams are wider than their box at {width} in {theme}")
                        if d["textMin"] < 4.5 or d["lineMin"] < 3 or d["smallest"] < 13:
                            fail(f"diagram measure in {theme} at {width}: {d}")
                    safely(f"diagrams in {theme} at {width}", one)

        section("Diagrams", diagrams)

        # -------------------------------------------------------------- hover, search and headings
        def states():
            lines.append("| Theme | State | Lowest ratio | Needs |")
            lines.append("| --- | --- | --- | --- |")
            hovers = [
                ("tab link", ".md-tabs__link:not(.md-tabs__link--active)", 4.5),
                ("side navigation link", ".md-sidebar--primary .md-nav__item:not(.md-nav__item--section) > a.md-nav__link:not(.md-nav__link--active)", 4.5),
                ("contents link", ".md-sidebar--secondary .md-nav__link", 4.5),
                ("link in text", ".md-typeset p a[href]", 4.5),
                ("header button", ".md-header__option label:not([hidden])", 3),
                ("repository link", ".md-source", 4.5),
                ("copy button", ".md-code__button", 3),
                ("footer link", ".md-footer__link", 4.5),
                ("table scroll box", ".ph-table-scroll", 4.5),
            ]
            for theme in THEMES:
                ctx = new_context(theme, reduced_motion="reduce")
                pg = ctx.new_page()
                load(pg, PAGES["code"])
                for label, sel, need in hovers:
                    def hov():
                        loc = pg.locator(sel + ":visible").first
                        if not loc.count():
                            return
                        loc.scroll_into_view_if_needed()
                        loc.hover(timeout=4000)
                        low = min(r["ratio"] for r in pg.evaluate(JS_CONTRAST, loc.element_handle()))
                        lines.append(f"| {theme} | hover: {label} | {low:.2f} | {need} |")
                        if low < need:
                            fail(f"hover contrast {low:.2f} for {label} in {theme}")
                    safely(f"hover on {label} in {theme}", hov)

                def back_to_top():
                    pg.evaluate("window.scrollTo(0, 2500)")
                    pg.evaluate("window.scrollTo(0, 2000)")
                    pg.wait_for_timeout(400)
                    top = pg.locator(".md-top:visible")
                    if top.count():
                        top.first.hover(timeout=4000)
                        low = min(r["ratio"] for r in pg.evaluate(JS_CONTRAST, top.first.element_handle()))
                        lines.append(f"| {theme} | hover: back to top | {low:.2f} | 4.5 |")
                        if low < 4.5:
                            fail(f"hover contrast {low:.2f} for back to top in {theme}")
                safely(f"back to top in {theme}", back_to_top)

                def search():
                    load(pg, PAGES["home"])
                    pg.locator("input.md-search__input").first.click()
                    # the suggestion shown inside the box while a word is typed
                    pg.wait_for_timeout(1200)
                    pg.keyboard.type("aler", delay=40)
                    pg.wait_for_timeout(1200)
                    sug = pg.locator(".md-search__suggest")
                    if sug.count() and (sug.first.inner_text() or "").strip():
                        low = min(r["ratio"] for r in pg.evaluate(JS_CONTRAST, sug.first.element_handle()))
                        lines.append(f"| {theme} | search suggestion text | {low:.2f} | 4.5 |")
                        if low < 4.5:
                            fail(f"search suggestion text {low:.2f}:1 in {theme}")
                    else:
                        lines.append(f"| {theme} | search suggestion text | none shown | 4.5 |")
                    pg.fill("input.md-search__input", "")
                    search_for(pg, "alert")
                    panel = pg.locator(".md-search__output").first
                    rows = pg.evaluate(JS_CONTRAST, panel.element_handle())
                    low = min(r["ratio"] for r in rows) if rows else 0
                    smallest = min((r["size"] for r in rows), default=99)
                    lines.append(f"| {theme} | search panel with results ({len(rows)} styles, smallest {smallest:.1f}px) | {low:.2f} | 4.5 |")
                    if low < 4.5 or not rows:
                        fail(f"search panel contrast {low:.2f} in {theme}")
                    if smallest < 13:
                        fail(f"search panel text {smallest:.1f}px is under the 13px floor in {theme}")
                    res = pg.locator(".md-search-result__link").nth(1)
                    res.hover(timeout=4000)
                    low = min(r["ratio"] for r in pg.evaluate(JS_CONTRAST, res.element_handle()))
                    lines.append(f"| {theme} | search result under the pointer | {low:.2f} | 4.5 |")
                    if low < 4.5:
                        fail(f"hovered search result contrast {low:.2f} in {theme}")
                    pg.keyboard.press("ArrowDown")
                    pg.keyboard.press("ArrowDown")
                    info = pg.evaluate(JS_FOCUS)
                    cur = pg.locator(".md-search-result__link:focus")
                    if info and cur.count():
                        low = min(r["ratio"] for r in pg.evaluate(JS_CONTRAST, cur.first.element_handle()))
                        lines.append(f"| {theme} | search result under the keyboard (ring {info['width']:.0f}px, {info['ratio']:.1f}:1) | {low:.2f} | 4.5 |")
                        if low < 4.5 or not info["ringOk"] or info["ratio"] < 3:
                            fail(f"focused search result in {theme}: text {low:.2f} ring {info}")
                    else:
                        fail(f"no search result took focus from the keyboard in {theme}")
                    # the "more on this page" control
                    more = pg.locator(".md-search-result details > summary")
                    if more.count():
                        more.first.scroll_into_view_if_needed()
                        pg.keyboard.press("Tab")
                        for _ in range(40):
                            if pg.evaluate("document.activeElement.tagName") == "SUMMARY":
                                break
                            pg.keyboard.press("Tab")
                        info = pg.evaluate(JS_FOCUS)
                        if info and info["tag"] == "summary":
                            lines.append(f"| {theme} | search 'more on this page' control focus (ring {info['width']:.0f}px, {info['ratio']:.1f}:1) | - | 3 |")
                            if not info["ringOk"] or info["ratio"] < 3:
                                fail(f"the 'more on this page' control has no 3 px ring in {theme}: {info}")
                        else:
                            lines.append(f"| {theme} | search 'more on this page' control | not reached | 3 |")
                    else:
                        lines.append(f"| {theme} | search 'more on this page' control | none in the results | 3 |")
                safely(f"search states in {theme}", search)
                ctx.close()

        section("Hover and search states", states)

        # ----------------------------------------------------------------- the theme switch, headings, security
        def structure():
            ctx = new_context("light")
            pg = ctx.new_page()
            load(pg, PAGES["home"])
            before = pg.evaluate("document.body.dataset.mdColorScheme")
            pg.locator("label.md-header__button[for^='__palette']:visible").first.click()
            after = pg.evaluate("document.body.dataset.mdColorScheme")
            lines.append(f"- switch: {before} to {after}")
            if before == after:
                fail("the theme switch did not change the theme")
            load(pg, PAGES["home"])
            stored = pg.evaluate("document.body.dataset.mdColorScheme")
            lines.append(f"- choice kept on the next page: {stored}")
            sw = pg.evaluate("""() => { const l = document.querySelector('.md-header__option label:not([hidden])');
              const radios = [...document.querySelectorAll('.md-header__option input')];
              return { role: l && l.getAttribute('role'), name: l && l.getAttribute('aria-label'), radiosHidden: radios.every(r => r.getAttribute('aria-hidden') === 'true' && r.tabIndex === -1) } }""")
            lines.append(f"- switch for a reader: role {sw['role']}, name '{sw['name']}', radios out of the tab order {sw['radiosHidden']}")
            if sw["role"] != "button" or not sw["name"] or not sw["radiosHidden"]:
                fail(f"the theme switch is announced as a radio, not as a button: {sw}")
            load(pg, PAGES["long-reference"])
            hl = pg.evaluate("""() => [...document.querySelectorAll('h1 a.headerlink, h2 a.headerlink, h3 a.headerlink, h4 a.headerlink')].map(a => ({
              label: a.getAttribute('aria-label') || '', head: a.parentElement.textContent.replace(a.textContent, '').trim(), tab: a.getAttribute('tabindex') }))""")
            generic = [h for h in hl if not h["label"].endswith(h["head"]) or h["tab"] != "-1" or h["label"] == "Link to this section"]
            lines.append(f"- heading links on the long page: {len(hl)}, wrongly named or in the tab order: {len(generic)}")
            if generic:
                fail(f"{len(generic)} heading links are not named from their heading or are tab stops")
            anchors = pg.evaluate("document.querySelectorAll('a[id^=\"__codelineno\"]').length")
            lines.append(f"- empty code line anchors: {anchors}")
            if anchors:
                fail(f"{anchors} empty code line anchors")
            ctx.close()
            # a picture in a page cannot come from another site, even from a diagram label
            ctx = new_context("light")
            pg = ctx.new_page()
            load(pg, PAGES["home"])
            blocked = pg.evaluate("""() => new Promise(res => {
              document.addEventListener('securitypolicyviolation', e => res(true));
              const i = new Image(); i.src = 'http://127.0.0.1:9/ph-csp-probe.png'; document.body.appendChild(i);
              setTimeout(() => res(false), 2000); })""")
            lines.append(f"- an image from another origin: {'blocked by the content security policy' if blocked else 'NOT blocked'}")
            if not blocked:
                fail("the page lets an image load from another origin")
            for u in [u for u in foreign if 'ph-csp-probe' in u]:
                foreign.discard(u)
            ctx.close()
            # the unfilled placeholder guard, on the built pages
            hits = []
            for path in all_pages:
                text = open(os.path.join(args.site, path), encoding="utf-8").read()
                for m in re.finditer(r"\{\{\s*[A-Z][A-Z0-9_]*\s*\}\}", re.sub(r"<(pre|code)[^>]*>.*?</\1>", "", text, flags=re.S)):
                    hits.append(f"{path}: {m.group(0)}")
            lines.append(f"- unfilled placeholders in built pages: {len(hits)}")
            if hits and not args.allow_placeholders:
                fail("unfilled placeholders in built pages: " + ", ".join(hits[:8]))
            elif hits:
                lines.append("  (allowed for this run: " + ", ".join(hits) + ")")

        section("Switch, headings, content security policy and placeholders", structure)


        # ------------------------------------------------------------------------- the theme switch by keyboard
        def switch_keys():
            ctx = new_context("light")
            pg = ctx.new_page()
            load(pg, PAGES["home"])
            for key in ("Enter", "Space"):
                on = lambda: (pg.evaluate("document.activeElement.getAttribute('aria-label') || ''")).startswith("Switch to")
                for _ in range(12):
                    if on():
                        break
                    pg.keyboard.press("Tab")
                else:
                    fail("the theme switch never took focus")
                    break
                before = pg.evaluate("document.body.dataset.mdColorScheme")
                pg.keyboard.press(key)
                pg.wait_for_timeout(400)
                after = pg.evaluate("document.body.dataset.mdColorScheme")
                kept = pg.evaluate("(document.activeElement.getAttribute('aria-label') || '').startsWith('Switch to')")
                lines.append(f"- {key}: {before} to {after}, focus stays on the switch {kept}")
                if before == after or not kept:
                    fail(f"the theme switch does not work with {key} (changed {before != after}, focus kept {kept})")
            ctx.close()

        section("The theme switch by keyboard", switch_keys)

        # ------------------------------------------------------------------- Tab past the last link of the drawer
        def drawer_out():
            ctx = new_context("light", 390)
            pg = ctx.new_page()
            load(pg, PAGES["long-reference"])
            for _ in range(8):
                pg.keyboard.press("Tab")
                if "Navigation menu" in pg.evaluate("document.activeElement.getAttribute('aria-label') || ''"):
                    break
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(500)
            left = False
            for _ in range(80):
                pg.keyboard.press("Tab")
                pg.wait_for_timeout(30)
                inside = pg.evaluate("!!document.activeElement.closest('.md-sidebar--primary') || (document.activeElement.getAttribute('aria-label') || '').includes('Navigation menu')")
                if not inside:
                    left = True
                    break
            closed = not pg.evaluate("document.getElementById('__drawer').checked")
            seen = pg.evaluate("(() => { const r = document.activeElement.getBoundingClientRect(); return r.width > 0 && r.right > 0 && r.left < innerWidth && r.bottom > 0 && r.top < innerHeight; })()")
            lines.append(f"- focus left the drawer {left}, drawer closed {closed}, focus on something on screen {seen}")
            if not (left and closed and seen):
                fail("Tab past the last drawer link does not close the drawer onto visible content")
            ctx.close()

        section("Tab past the end of the open drawer", drawer_out)

        # ------------------------------------------------------------------- scripts off on a phone: the drawer
        def drawer_noscript():
            ctx = new_context("light", 390, java_script_enabled=False)
            pg = ctx.new_page()
            pg.goto(base + PAGES["long-reference"])
            found = False
            for _ in range(6):
                pg.keyboard.press("Tab")
                if pg.evaluate("document.activeElement.id") == "__drawer":
                    found = True
                    break
            ring = pg.evaluate("(() => { const l = document.querySelector('label.md-header__button[for=__drawer]'); const s = getComputedStyle(l); return s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 3; })()")
            pg.keyboard.press("Space")
            pg.wait_for_timeout(500)
            opened = pg.evaluate("document.getElementById('__drawer').checked")
            shown = pg.evaluate("(() => { const a = document.querySelector('.md-sidebar--primary a.md-nav__link'); const r = a.getBoundingClientRect(); return getComputedStyle(a).visibility === 'visible' && r.left >= 0 && r.right <= innerWidth && r.width > 0; })()")
            lines.append(f"- checkbox reached by keyboard {found}, ring on the menu label {ring}, Space opens {opened}, navigation on screen {shown}")
            if not (found and ring and opened and shown):
                fail(f"with scripts off on a phone the navigation cannot be opened by keyboard: reached {found} ring {ring} opened {opened} shown {shown}")
            ctx.close()

        section("Scripts off on a phone: the navigation drawer by keyboard", drawer_noscript)

        # --------------------------------------------------------------------------------- the line length of prose
        def measure():
            lines.append("| Width | Longest average line of a long paragraph (characters) |")
            lines.append("| --- | --- |")
            js = r"""() => { let worst = 0; for (const p of document.querySelectorAll('.md-typeset > p')) {
              const t = p.textContent.trim(); if (t.length < 400) continue;
              const lh = parseFloat(getComputedStyle(p).lineHeight); const n = Math.round(p.getBoundingClientRect().height / lh);
              if (n >= 3) worst = Math.max(worst, t.length / n); } return worst; }"""
            for width in (1219, 1440, 1920):
                ctx = new_context("light", width)
                pg = ctx.new_page()
                load(pg, PAGES["long-reference"])
                load(pg, PAGES["architecture"])
                w = pg.evaluate(js)
                lines.append(f"| {width} | {w:.0f} |")
                if w > 85:
                    fail(f"prose runs to {w:.0f} characters a line at {width}")
                ctx.close()

        section("Measure of prose", measure)

        # ---------------------------------------------------------------------------- search returns, origins
        def search_and_origins():
            ctx = new_context("light")
            pg = ctx.new_page()
            load(pg, PAGES["home"])
            pg.locator("input.md-search__input").first.click()
            search_for(pg, "alert")
            hits = pg.locator(".md-search-result__item").count()
            lines.append(f"- search for 'alert': {hits} results")
            if hits == 0:
                fail("search returned nothing")
            ctx.close()
            lines.append(f"- requests to any other origin across the whole run: {len(foreign)}")
            for u in sorted(foreign)[:10]:
                fail(f"request to another origin: {u}")

        section("Search and other origins", search_and_origins)

        # ----------------------------------------------------------------------------------------- screenshots
        shots = []
        if not args.no_shots:
            def screenshots():
                for theme in THEMES:
                    for width in SHOT_WIDTHS:
                        ctx = new_context(theme, width)
                        for name in CORE + ["architecture"]:
                            def one():
                                pg = ctx.new_page()
                                try:
                                    load(pg, PAGES[name])
                                    fn = os.path.join(args.out, "screenshots", f"{name}-{width}-{theme}.png")
                                    pg.screenshot(path=fn)
                                    shots.append(fn)
                                    target = pg.locator(".ph-table-scroll, .highlight, .ph-diagram[data-ready]").first
                                    if name != "home" and target.count():
                                        target.scroll_into_view_if_needed()
                                        pg.evaluate("window.scrollBy(0, -140)")
                                        pg.wait_for_timeout(150)
                                        fn2 = os.path.join(args.out, "screenshots", f"{name}-{width}-{theme}-inside.png")
                                        pg.screenshot(path=fn2)
                                        shots.append(fn2)
                                finally:
                                    pg.close()
                            safely(f"screenshot of {name} at {width} in {theme}", one)
                        ctx.close()
                # scripts off with a dark system theme
                ctx = new_context("dark", 1440, java_script_enabled=False)
                for name in ("home", "code"):
                    pg = ctx.new_page()
                    pg.goto(base + PAGES[name])
                    fn = os.path.join(args.out, "screenshots", f"{name}-1440-dark-scripts-off.png")
                    pg.screenshot(path=fn)
                    shots.append(fn)
                    pg.close()
                ctx.close()
                lines.append(f"{len(shots)} files in {os.path.join(args.out, 'screenshots')}")

            section("Screenshots", screenshots)
        browser.close()
    srv.shutdown()

    summary = ["# Documentation site check\n", f"Result: {'PASS' if not failures else 'FAIL (' + str(len(failures)) + ' findings)'}\n"]
    report = "\n".join(summary + lines)
    with open(os.path.join(args.out, "check-report.md"), "w") as f:
        f.write(report)
    with open(os.path.join(args.out, "check-failures.json"), "w") as f:
        json.dump(failures, f, indent=1)
    print(report)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
