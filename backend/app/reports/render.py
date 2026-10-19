"""Render the quarterly review pack to HTML with Jinja2.

RM text is only ever passed as template *variables* (never concatenated into the
template source), the environment is sandboxed and autoescaped, and templates
load only from the trusted templates/ directory.
"""
import re
from hashlib import sha256
from pathlib import Path

from jinja2 import FileSystemLoader, StrictUndefined, select_autoescape
from jinja2.sandbox import SandboxedEnvironment
from markupsafe import Markup, escape

from .charts import CHARTS

TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_NAME = "review_pack.html.j2"
_BULLET = re.compile(r"^\s*(•|-|\*)\s+")
_TAG = re.compile(r"(\[[A-Z]+[A-Za-z0-9-]*\])")
_DATA_IMG = re.compile(r"^data:image/(png|jpeg|jpg|gif|webp);base64,[A-Za-z0-9+/=]+$")


def _bullets(text: str) -> list[str]:
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if any(_BULLET.match(l) for l in lines):
        return [_BULLET.sub("", l) for l in lines]
    out: list[str] = []
    for l in lines:
        out += [p.rstrip(".").strip() for p in re.split(r"(?<=\.)\s+(?=[A-Z\[])", l)]
    return [o for o in out if o]


def _tagged(text: str) -> Markup:
    """Escape text, turning [TAG-123] markers into citation chips."""
    parts = _TAG.split(text)
    return Markup("").join(
        Markup('<span class="cite">{}</span>').format(p[1:-1]) if _TAG.fullmatch(p) else escape(p) for p in parts
    )


def _env() -> SandboxedEnvironment:
    env = SandboxedEnvironment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"], default=True),
        undefined=StrictUndefined,
    )
    env.filters["bullets"] = _bullets
    env.filters["tagged"] = _tagged
    return env


def render_review_pack(payload: dict) -> str:
    env = _env()
    data = {"allocation": payload["allocation"]}

    def chart(name: str) -> Markup:
        if name not in CHARTS:
            raise KeyError(f"Unknown chart placeholder: {name}")
        fn, key = CHARTS[name]
        return fn(data[key])

    sigs = {
        role: s for role, s in payload.get("signatures", {}).items() if _DATA_IMG.match(s.get("data_url", ""))
    }
    defaults = {"text": "", "wide": False, "chart": None, "kind": None}
    sections = [{**defaults, **s} for s in payload["sections"]]
    template = env.get_template(TEMPLATE_NAME)
    return template.render(
        doc=payload["doc"],
        sections=sections,
        signatures=sigs,
        chart=chart,
    )


def template_version() -> str:
    return sha256((TEMPLATE_DIR / TEMPLATE_NAME).read_bytes()).hexdigest()[:12]
