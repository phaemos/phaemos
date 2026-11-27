# Docs

Technical documentation for PHAEMOS. These files also build into the documentation site with `make docs`,
starting from [index.md](index.md).

| File | Description |
| --- | --- |
| [index.md](index.md) | The documentation home page |
| [architecture.md](architecture.md) | System diagram, data flow, deployment targets, background tasks |
| [development.md](development.md) | Running locally, the smoke test, the simulator and the test commands |
| [api-reference.md](api-reference.md) | Every REST endpoint with its auth requirements and request and response shapes |
| [schema.md](schema.md) | PostgreSQL table definitions |
| [security.md](security.md) | The security controls |
| [releases.md](releases.md) | Tagging a release and the changelog check |
| [repositories.md](repositories.md) | The monorepo layout, the published component repositories and how publishing works |
| [tech-stack.md](tech-stack.md) | Every language and tool by layer, plus the four boards |
| [deployment.md](deployment.md) | DigitalOcean and Vercel deployment guide |
| [scalability.md](scalability.md) | Scaling guide from a single server to a distributed setup |
| [sensor_reference.md](sensor_reference.md) | Every sensor with its specs, calibration and expected reading ranges |

## Building and checking the site

The site is MkDocs with the Material theme. Everything the look needs is in the repository: the styles in
`stylesheets/phaemos.css`, the page templates and the build hook in `overrides/` and the typefaces in `assets/fonts`
(Exo 2, Manrope and IBM Plex Mono under the SIL Open Font Licence, see `assets/fonts/NOTICE.txt`) and the diagram library in
`assets/vendor/mermaid` (MIT, version and SHA-256 in its `NOTICE.txt`), which loads only on a page with a diagram. The site makes no request to any
other origin, so there is no font host and no analytics.

Build and preview it from the repository root. Use a virtual environment so nothing is installed system-wide.

```bash
python3 -m venv .venv-docs
.venv-docs/bin/pip install -r requirements-docs.txt
.venv-docs/bin/mkdocs build --strict -d /tmp/phaemos-site
.venv-docs/bin/mkdocs serve --dev-addr 127.0.0.1:24800
```

Run `make openapi` before a strict build. It writes `docs/openapi.json` and `docs/api-routes.md`, which two pages link to.
Without them the strict build stops on four broken links in the API pages.

To check the built site in a real browser, add Playwright and run the check script. It serves the folder on a local port
and reports contrast of every text style in both themes, target sizes, focus rings on every tab stop, sideways scroll at
320, 390, 768 and 1440 pixels at 100 and 200 per cent text, requests to other origins, reduced motion and reading with
scripts off. It also saves screenshots. It exits with 1 when any check fails.

`make docs-check` does the install, a strict build into a scratch folder and the check in one go. By hand:

```bash
.venv-docs/bin/pip install -r requirements-docs-check.txt
.venv-docs/bin/python docs/overrides/check_site.py --site /tmp/phaemos-site --out /tmp/phaemos-site-check
```

The script uses the Chromium that Playwright has already downloaded. If there is none, run
`.venv-docs/bin/playwright install chromium` once or point `CHROMIUM_PATH` at a Chromium or Chrome binary.

When you change a colour, check the pair in the report before you commit. Body text should reach 7:1 and nothing may fall
under 4.5:1. Links, icons, borders that carry meaning and focus rings need 3:1.

### Marking figures that come from simulated data

Put this admonition directly above any block of catch, false-alert or timing figures that came from the simulator. It has a
word (the title), an amber bar and a flask icon, so the kind never depends on colour alone.

```markdown
!!! simulated "Figures from simulated data"
    These figures come from simulated machines. No real machine has been measured.
```

The text under the title is indented four spaces and can say what was simulated. Leave the title out (`!!! simulated`) to
get the single word "Simulated".

### What the content security policy covers

Every page carries a policy in its head. It allows scripts only from this site and by hash for the page's own inline scripts
(the hashes are added at build time). It allows web workers from this site and from `blob:` (the theme's search runs in
one). It allows images only from this site and from `data:` addresses. It forbids plug-ins and limits `base` and form
targets to this site. It does not limit styles, fonts, frames or network requests: the theme sets styles inline and a
style policy would need an exception that makes it meaningless. The check script confirms that an image from another
origin is blocked and that no page raises a policy violation.

With scripts off on a phone the menu works from the keyboard through the theme's own hidden checkbox: Tab reaches it, Space
opens the drawer and the ring shows on the menu button. That checkbox comes before the skip link in that case.
