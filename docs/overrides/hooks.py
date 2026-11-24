"""Build hooks for the documentation site."""
import base64
import hashlib
import html as htmllib
import logging
import os
import re
from html.parser import HTMLParser

from mkdocs.exceptions import PluginError

log = logging.getLogger("mkdocs.hooks.phaemos")

# ---------------------------------------------------------------------------------------------------------------------
# a placeholder such as {{NAME}} means a page was published before its owner filled it in. The build stops and names the line;
# set PHAEMOS_DOCS_ALLOW_PLACEHOLDERS=1 only to build a scratch copy for a check. Never for a published build.
_PLACEHOLDER = re.compile(r"\{\{\s*[A-Z][A-Z0-9_]*\s*\}\}")


def on_page_markdown(markdown, page, **kwargs):
    found = []
    for number, line in enumerate(markdown.split("\n"), 1):
        for hit in _PLACEHOLDER.findall(line):
            found.append(f"{page.file.src_path}:{number}: {hit}")
    if found and os.environ.get("PHAEMOS_DOCS_ALLOW_PLACEHOLDERS") != "1":
        raise PluginError("unfilled placeholder in a published page, fill it before building:\n  " + "\n  ".join(found))
    return markdown


# ---------------------------------------------------------------------------------------------------------------------
# a text alternative for each diagram: a name and a paragraph that says what it shows. Keyed by page and position.
DIAGRAMS = {
    "architecture.md": [
        (
            "System diagram",
            "Sensor nodes feed the FastAPI backend. The ESP32 hub merges the Black Pill (UART at 115200 baud) and the Arduino "
            "Nano (serial CSV at 9600 baud) and posts every 5 seconds. The Pico 2W posts over Wi-Fi every 5 seconds. The "
            "optional Rust edge gateway reads JSON lines over serial and forwards readings with retries. The Python SDK, the "
            "simulator and the Go CLI also post. Inside the backend each reading passes from ingest to the model, to the alert "
            "rules and on to notifications and to the WebSocket broadcast. The reading and its score are saved in "
            "PostgreSQL and the backend checks Redis for status. The WebSocket feeds the Next.js dashboard.",
        ),
        (
            "Ingesting a reading, in order",
            "A node or edge gateway posts to the API with its X-API-Key. The API looks the device up by its key, stops any "
            "sensor the post names in faults and asks the model to score the reading only when every feature the model needs "
            "is present. It saves the reading with its score, anomaly flag and the node's health fields, then checks the "
            "device's rules unless a maintenance window is open. A sustained spell of anomalous readings raises one alert and "
            "opens a ticket. Notifications go out after the response is sent. The API broadcasts the reading over WebSocket, "
            "and the dashboard polls for the latest reading every 5 seconds as a fallback.",
        ),
        (
            "Sign-in sequence",
            "The browser posts the email and password to the login route. An account without two-factor authentication gets a "
            "15-minute access token and a 7-day refresh cookie. An account with two-factor authentication gets a 5-minute "
            "sign-in challenge and no session, then posts the challenge with a code to the verify route and receives the same "
            "token and cookie. Later requests carry the access token as a Bearer header. The refresh route takes the cookie "
            "alone and returns a new 15-minute access token.",
        ),
        (
            "Target deployment layout",
            "Users reach the Vercel dashboard and docs site, which call Nginx. Sensor nodes post to Nginx. On the VPS, under "
            "Docker Compose, Nginx is the reverse proxy in front of FastAPI, which uses PostgreSQL and Redis. A hosted status "
            "page checks Nginx from outside.",
        ),
    ]
}

_DIAGRAM = re.compile(r'<div class="ph-diagram">(.*?)</div>', re.S)

# ---------------------------------------------------------------------------------------------------------------------
_TABLE = re.compile(r"<table(?P<attrs>[^>]*)>(?P<body>.*?)</table>", re.S)
_HEADING = re.compile(r"<h(?P<n>[1-6])(?P<attrs>[^>]*)>(?P<text>.*?)<a class=\"headerlink\"(?P<link>[^>]*)>(?P<mark>.*?)</a></h[1-6]>", re.S)
_ANY = re.compile(
    r"(?P<heading><h[1-6][^>]*>.*?</h[1-6]>)"
    r"|(?P<table><table[^>]*>.*?</table>)"
    r"|(?P<diagram><div class=\"ph-diagram\">.*?</div>)",
    re.S,
)
# a cell that holds only a link is a target a reader aims at, so it gets a class that makes the link 44 px high
_LINK_CELL = re.compile(r"<td>(<a [^>]*>[^<]*</a>)</td>")
# GitHub's alert form (> [!WARNING]) reads as a plain quote here. This turns it into the theme's admonition, which carries a
# word and an icon as well as a colour. The page text is not touched.
_ALERT = re.compile(r"<blockquote>\s*<p>\[!(?P<kind>NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(?P<rest>.*?)</blockquote>", re.S)
_ALERT_CLASS = {"NOTE": "note", "TIP": "tip", "IMPORTANT": "info important", "WARNING": "warning", "CAUTION": "danger caution"}


def _plain(fragment):
    return htmllib.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _alert(match):
    kind = match.group("kind")
    return (
        f'<div class="admonition {_ALERT_CLASS[kind]}"><p class="admonition-title">{kind.capitalize()}</p>'
        f'<p>{match.group("rest")}</div>'
    )


def on_page_content(html, page, **kwargs):
    html = _ALERT.sub(_alert, html)
    src = page.file.src_path
    plan = DIAGRAMS.get(src, [])
    state = {"heading": page.title or "Table", "diagram": 0}

    def step(match):
        if match.group("heading"):
            text = match.group("heading")
            found = _HEADING.match(text)
            if not found:
                return text
            name = _plain(found.group("text"))
            state["heading"] = name
            # the link beside a heading is named for its heading. It stays out of the tab order: the contents list on the
            # page already reaches every heading by keyboard and 130 near-identical stops on a long page would only slow a
            # keyboard reader. Touch and pointer readers and screen reader browse mode still reach it.
            label = htmllib.escape(f"Link to section: {name}", quote=True)
            return (
                f'<h{found.group("n")}{found.group("attrs")}>{found.group("text")}'
                f'<a class="headerlink"{found.group("link")} aria-label="{label}" tabindex="-1">{found.group("mark")}</a>'
                f'</h{found.group("n")}>'
            )
        if match.group("table"):
            tbl = _TABLE.match(match.group("table"))
            if "class=" in tbl.group("attrs"):
                return match.group(0)
            name = htmllib.escape(state["heading"], quote=True)
            return (
                '<p class="ph-table-hint" aria-hidden="true">Scrolls sideways for more columns</p>'
                f'<div class="ph-table-scroll" data-heading="{name}" role="region" tabindex="0" '
                f'aria-label="Table: {name}. Scrolls sideways for more columns.">'
                f'<table class="ph-table"{tbl.group("attrs")}>{tbl.group("body")}</table></div>'
            )
        index = state["diagram"]
        state["diagram"] += 1
        body = _DIAGRAM.match(match.group("diagram")).group(1)
        if index < len(plan):
            title, summary = plan[index]
        else:
            log.warning("%s: diagram %d has no text alternative. Add one to DIAGRAMS in docs/overrides/hooks.py", src, index + 1)
            title, summary = f"Diagram {index + 1}", ""
        sid = f"ph-summary-{index + 1}"
        caption = f'<figcaption id="{sid}" class="ph-diagram__summary"><strong>What the diagram shows.</strong> {htmllib.escape(summary)}</figcaption>' if summary else ""
        return (
            f'<figure class="ph-figure" aria-label="{htmllib.escape(title, quote=True)}"><div class="ph-diagram" data-title="{htmllib.escape(title, quote=True)}" data-summary-id="{sid if summary else ""}">{body}</div>'
            f"{caption}</figure>"
        )

    html = _ANY.sub(step, html)
    return _LINK_CELL.sub(r'<td class="ph-link-cell">\1</td>', html)


# ---------------------------------------------------------------------------------------------------------------------
# the content security policy in the page head (overrides/main.html) is finished here. Scripts may come only from this site
# and from the page's own inline scripts, each allowed by its hash, so no inline exception covers a script nobody wrote.
class _InlineScripts(HTMLParser):
    """The body of every inline script, found by an HTML parser so a tag in capitals or an end tag with a space in it is
    read the way a browser reads it. A script with a src or a JSON data block runs nothing inline and is left out."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.bodies = []
        self._open = None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            names = {name: (value or "") for name, value in attrs}
            runs_inline = "src" not in names and names.get("type", "").strip().lower() != "application/json"
            self._open = [] if runs_inline else None

    def handle_data(self, data):
        if self._open is not None:
            self._open.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._open is not None:
            self.bodies.append("".join(self._open))
            self._open = None


def _inline_script_bodies(output):
    parser = _InlineScripts()
    parser.feed(output)
    parser.close()
    return parser.bodies


# ---------------------------------------------------------------------------------------------------------------------
# the site name in the header is the drawn wordmark, the same vectors as the website. The shapes are read from the brand file
# in assets/icons, so there is one drawing and written into the page as an inline image named with the visible word. No text
# is hidden or recoloured: a screen reader hears "PHAEMOS" from the image's name and the letters take the header's text colour.
_WORDMARK_FILE = os.path.join(os.path.dirname(__file__), "..", "assets", "icons", "phaemos-wordmark-light.svg")
_TOPIC = re.compile(r'(<div class="md-header__topic">\s*<span class="md-ellipsis">)\s*(?P<name>[^<]+?)\s*(</span>)')


def _wordmark(name):
    with open(_WORDMARK_FILE, encoding="utf-8") as f:
        letters, mark = re.findall(r'\sd="([^"]+)"', f.read())[:2]
    return (
        f'<svg class="ph-wordmark" viewBox="0 0 613 68" role="img" aria-label="{htmllib.escape(name)}" focusable="false">'
        f'<path fill="currentColor" fill-rule="evenodd" d="{letters}"/><path class="ph-wordmark__mark" d="{mark}"/></svg>'
    )


def on_post_page(output, page, config):
    output = _TOPIC.sub(lambda m: m.group(1) + _wordmark(m.group("name")) + m.group(3), output, count=1)
    hashes = []
    for body in _inline_script_bodies(output):
        digest = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode()
        hashes.append(f"'sha256-{digest}'")
    return output.replace("__SCRIPT_HASHES__", " ".join(sorted(set(hashes))))
