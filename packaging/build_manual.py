"""Build the standalone user manual. Use --pdf with ReportLab for the A4 edition."""
import argparse
import base64
from html import escape
from itertools import groupby
from pathlib import Path
import re

DOCS = Path(__file__).resolve().parents[1] / "docs"
MANUAL = DOCS / "WINDOWS_USER_MANUAL.md"
PDF = DOCS / "Guia-de-usuario-CONFA-0.6.0.pdf"


def blocks():
    for raw in MANUAL.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        image = re.fullmatch(r"!\[(.*?)\]\(([^)]+)\)", line)
        if image:
            yield "image", image.groups()
        elif line.startswith("### "):
            yield "h3", line[4:]
        elif line.startswith("## "):
            yield "h2", line[3:]
        elif line.startswith("# "):
            yield "h1", line[2:]
        elif re.match(r"\d+\. ", line):
            yield "ol", line.split(". ", 1)[1]
        elif line.startswith("- "):
            yield "ul", line[2:]
        else:
            yield "p", line


def inline(value):
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escape(value))


def make_html(items):
    html = ['<!doctype html><html lang="es"><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            '<title>CONFA · Guía de usuario para Windows</title>',
            """<style>
            *{box-sizing:border-box}body{max-width:54rem;margin:2.5rem auto;padding:0 1.5rem;
            color:#172535;font:18px/1.5 system-ui,sans-serif}h1{font-size:3.4rem}
            h1,h2,h3{color:#115d58;line-height:1.18}h2{margin-top:3rem}h3{margin:1.5rem 0 .6rem}
            li{margin:.5rem 0}figure{margin:1rem 0;background:#f4f7f8;padding:.8rem}
            img{display:block;max-width:100%;height:auto;max-height:28rem;margin:auto}
            figcaption{font-size:.88em;margin:.5rem 0 0}p{margin:.6rem 0}
            @page{size:A4;margin:17mm}@media print{body{font-size:11pt;max-width:none;margin:0;padding:0}
            h2{break-before:page;margin-top:0}figure{break-inside:avoid}img{max-height:82mm}h3{break-after:avoid}}
            </style><main>"""]
    for kind, group in groupby(items, key=lambda pair: pair[0]):
        if kind in ("ol", "ul"):
            html.append(f"<{kind}>")
        for _, value in group:
            if kind == "image":
                caption, filename = value
                encoded = base64.b64encode((DOCS / filename).read_bytes()).decode("ascii")
                html.append(f'<figure><img alt="{escape(caption)}" src="data:image/png;base64,{encoded}">'
                            f'<figcaption>{escape(caption)}</figcaption></figure>')
            else:
                tag = "li" if kind in ("ol", "ul") else kind
                html.append(f"<{tag}>{inline(value)}</{tag}>")
        if kind in ("ol", "ul"):
            html.append(f"</{kind}>")
    (DOCS / "Manual.html").write_text("\n".join(html + ["</main></html>"]), encoding="utf-8")


def make_pdf(items):
    from reportlab import rl_config
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import Paragraph

    font_dir = next(Path(p) for p in rl_config.TTFSearchPath if (Path(p) / "Vera.ttf").is_file())
    for name, filename in (("Guide", "Vera.ttf"), ("GuideBold", "VeraBd.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(font_dir / filename)))
    pdfmetrics.registerFontFamily("Guide", normal="Guide", bold="GuideBold")
    canvas = Canvas(str(PDF), pagesize=A4, invariant=True)
    canvas.setTitle("CONFA 0.6.0 · Guía de usuario para Windows")
    canvas.setAuthor("Bloj Gustavo Ivan, Domfrocht Julian Davico, Petrelli Maximo Francesco, Valdez Manuel Ricardo")
    w, h = A4
    margin = 46
    width = w - 2 * margin
    green, ink, gray = "#105e58", "#182a36", "#405765"
    pages = []
    for kind, value in items:
        if kind in ("h1", "h2"):
            pages.append([])
        pages[-1].append((kind, value))
    for page_no, page in enumerate(pages, 1):
        y = h - 66
        def para(value, size=11.5, leading=16.5, *, bold=False, color=ink, after=7, indent=0):
            nonlocal y
            style = ParagraphStyle("guide", fontName="GuideBold" if bold else "Guide",
                                   fontSize=size, leading=leading, textColor=colors.HexColor(color),
                                   alignment=TA_LEFT)
            p = Paragraph(value.replace(" → ", " › "), style)
            _, height = p.wrap(width - indent, h)
            y -= height
            p.drawOn(canvas, margin + indent, y)
            y -= after

        canvas.setFont("GuideBold", 9)
        canvas.setFillColor(colors.HexColor(green))
        canvas.drawString(margin, h-37, "CONFA   /   ACCESIBILIDAD EN WINDOWS")
        canvas.setStrokeColor(colors.HexColor("#b6ceca"))
        canvas.line(margin, h-46, w-margin, h-46)
        canvas.bookmarkPage(f"p{page_no}")
        canvas.addOutlineEntry(page[0][1], f"p{page_no}", 0)
        for kind, group in groupby(page, key=lambda pair: pair[0]):
            for number, (_, value) in enumerate(group, 1):
                if kind == "image":
                    caption, filename = value
                    img = ImageReader(str(DOCS / filename))
                    iw, ih = img.getSize()
                    max_height = 266 if page_no == 1 else 235
                    if filename.endswith("metodo.png"):
                        max_height = 85
                    elif filename.endswith("bordes.png"):
                        max_height = 125
                    scale = min(width / iw, max_height / ih, 0.95)
                    pw, ph = iw * scale, ih * scale
                    y -= ph + 4
                    canvas.drawImage(img, margin+(width-pw)/2, y, pw, ph, mask="auto")
                    y -= 5
                    para(escape(caption), 9.2, 12.8, color=gray, after=12)
                elif kind == "h1":
                    para(value, 38, 46, bold=True, color=green, after=3)
                elif kind == "h2":
                    para(inline(value), 23, 28, bold=True, color=green, after=14)
                elif kind == "h3":
                    y -= 4
                    para(inline(value), 13, 17, bold=True, color=green, after=5)
                elif kind in ("ul","ol"):
                    canvas.setFont("GuideBold", 10.4)
                    canvas.setFillColor(colors.HexColor(green))
                    canvas.drawString(margin, y-12, f"{number}." if kind=="ol" else "•")
                    para(inline(value), indent=21, after=8)
                else:
                    para(inline(value))
        if y < 51:
            raise ValueError(f"El contenido de la página {page_no} invade el pie ({y:.1f}).")
        canvas.line(margin, 42, w-margin, 42)
        canvas.setFont("Guide", 8.5)
        canvas.setFillColor(colors.HexColor(gray))
        canvas.drawString(margin, 27, "Guía de usuario   ·   Versión 0.6.0")
        canvas.drawRightString(w-margin, 27, f"{page_no} / {len(pages)}")
        canvas.showPage()
    canvas.save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", action="store_true", help="Generar también la guía A4 con ReportLab")
    args = parser.parse_args()
    contents = list(blocks())
    make_html(contents)
    if args.pdf:
        make_pdf(contents)
