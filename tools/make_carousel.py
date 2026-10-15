"""
Carousel announcing the FMU Manipulation Toolbox 2.0: 1080 x 1350 slides (4:5), written into one directory as

- one PDF, the format of a LinkedIn "document" post;
- PNG files, a preview of the pages;
- WebP files, the slides shown on the page "What's new in 2.0" of the documentation (`docs/assets/release-2.0/`).

    python tools/make_carousel.py --out DIR

Texts and slides are in SLIDES below; the images come from the documentation and the resources of the package.
Requires PySide6 (with the `webp` image format plugin of Qt, shipped with the PySide6 wheels).
"""

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, QPointF, QSizeF, QMarginsF
from PySide6.QtGui import (QGuiApplication, QImage, QPainter, QColor, QFont, QPainterPath, QPdfWriter, QPageSize,
                           QPageLayout, QLinearGradient, QPen, QFontMetricsF)

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "fmu_manipulation_toolbox" / "resources"
DOC = ROOT / "docs"

W, H = 1080, 1350
MARGIN = 80
WEBP_QUALITY = 85

# Colours of the application (gui/style.py)
BG_TOP, BG_BOTTOM = QColor("#3a3d41"), QColor("#232429")
PANEL = QColor("#282830")
TEXT = QColor("#e6e6e6")
MUTED = QColor("#a9aeb0")
BLUE, GREEN, PURPLE, ORANGE, RED = (QColor("#4571a4"), QColor("#4e6749"), QColor("#564967"), QColor("#98763f"),
                                    QColor("#692e2e"))
LIGHT = {"blue": QColor("#7fa8db"), "green": QColor("#8fc47a"), "purple": QColor("#b39ddb"),
         "orange": QColor("#e0b050"), "red": QColor("#e5735f")}

FONT = "Verdana"
MONO = "Menlo" if sys.platform == "darwin" else "Consolas"


def font(size, bold=False, family=FONT):
    f = QFont(family)
    f.setPixelSize(size)
    f.setBold(bold)
    return f


def image(path) -> QImage:
    img = QImage(str(path))
    if img.isNull():
        raise FileNotFoundError(path)
    return img


# ── Drawing helpers ─────────────────────────────────────────────────────

def background(p: QPainter, accent: QColor, number: int, total: int):
    gradient = QLinearGradient(0, 0, 0, H)
    gradient.setColorAt(0, BG_TOP)
    gradient.setColorAt(1, BG_BOTTOM)
    p.fillRect(QRectF(0, 0, W, H), gradient)
    p.fillRect(QRectF(0, 0, W, 14), accent)
    # footer: logo, page number
    logo = image(RES / "fmu_manipulation_toolbox.png")
    p.drawImage(QRectF(MARGIN, H - 92, 220, 220 * logo.height() / logo.width()), logo)
    p.setFont(font(24))
    p.setPen(MUTED)
    p.drawText(QRectF(W - MARGIN - 200, H - 100, 200, 50), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
               f"{number} / {total}")


def text(p: QPainter, rect: QRectF, value: str, size: int, color=TEXT, bold=False, align=Qt.AlignmentFlag.AlignLeft,
         family=FONT) -> float:
    """Draw wrapped text in *rect*; return the height used."""
    f = font(size, bold, family)
    p.setFont(f)
    p.setPen(color)
    flags = align | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap
    bound = QFontMetricsF(f).boundingRect(rect, flags, value)
    p.drawText(rect, flags, value)
    return bound.height()


def kicker(p: QPainter, y: float, label: str, color: QColor) -> float:
    p.setFont(font(26, True))
    width = QFontMetricsF(p.font()).horizontalAdvance(label) + 40
    rect = QRectF(MARGIN, y, width, 50)
    path = QPainterPath()
    path.addRoundedRect(rect, 25, 25)
    p.fillPath(path, color)
    p.setPen(TEXT)
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
    return y + 50


def bullets(p: QPainter, y: float, items: list[str], color: QColor, size=34, spacing=26) -> float:
    for item in items:
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(MARGIN + 10, y + size * 0.62), 8, 8)
        y += text(p, QRectF(MARGIN + 40, y, W - 2 * MARGIN - 40, 400), item, size) + spacing
    return y


def screenshot(p: QPainter, img: QImage, rect: QRectF, source: QRectF | None = None, radius=18):
    """Draw *img* (or its part *source*, in pixels) fitted in *rect*, with rounded corners and a shadow."""
    source = source or QRectF(0, 0, img.width(), img.height())
    scale = min(rect.width() / source.width(), rect.height() / source.height())
    size = QSizeF(source.width() * scale, source.height() * scale)
    target = QRectF(rect.x() + (rect.width() - size.width()) / 2, rect.y(), size.width(), size.height())
    for i, alpha in ((14, 40), (8, 60), (3, 90)):
        shadow = QPainterPath()
        shadow.addRoundedRect(target.adjusted(-i, -i + 10, i, i + 10), radius + i, radius + i)
        p.fillPath(shadow, QColor(0, 0, 0, alpha))
    clip = QPainterPath()
    clip.addRoundedRect(target, radius, radius)
    p.save()
    p.setClipPath(clip)
    p.drawImage(target, img, source)
    p.restore()
    p.setPen(QPen(QColor("#5a5e63"), 2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(clip)
    return target.bottom()


def bubble(p: QPainter, rect: QRectF, value: str, fill: QColor, label: str, label_color: QColor) -> float:
    f = font(30)
    inner = rect.adjusted(36, 66, -36, 0)
    inner.setHeight(400)
    height = QFontMetricsF(f).boundingRect(inner, Qt.TextFlag.TextWordWrap, value).height() + 66 + 34
    frame = QRectF(rect.x(), rect.y(), rect.width(), height)
    path = QPainterPath()
    path.addRoundedRect(frame, 28, 28)
    p.fillPath(path, fill)
    text(p, QRectF(frame.x() + 36, frame.y() + 22, frame.width() - 72, 40), label, 24, label_color, bold=True)
    text(p, inner, value, 30)
    return frame.bottom()


def box(p: QPainter, rect: QRectF, title: str, subtitle: str, fill: QColor):
    path = QPainterPath()
    path.addRoundedRect(rect, 22, 22)
    p.fillPath(path, fill)
    text(p, rect.adjusted(20, 26, -20, 0), title, 32, bold=True, align=Qt.AlignmentFlag.AlignHCenter)
    text(p, rect.adjusted(20, 76, -20, 0), subtitle, 24, MUTED if fill == PANEL else TEXT,
         align=Qt.AlignmentFlag.AlignHCenter)


def code(p: QPainter, rect: QRectF, lines: list[tuple[str, str]]) -> float:
    path = QPainterPath()
    path.addRoundedRect(rect, 22, 22)
    p.fillPath(path, PANEL)
    y = rect.y() + 34
    for command, comment in lines:
        text(p, QRectF(rect.x() + 34, y, rect.width() - 68, 50), command, 27, LIGHT["green"], family=MONO)
        text(p, QRectF(rect.x() + 34, y + 40, rect.width() - 68, 50), comment, 22, MUTED)
        y += 98
    return rect.bottom()


def title_block(p, y, kick, kick_color, title, subtitle=None):
    y = kicker(p, y, kick, kick_color) + 34
    y += text(p, QRectF(MARGIN, y, W - 2 * MARGIN, 300), title, 60, bold=True) + 26
    if subtitle:
        y += text(p, QRectF(MARGIN, y, W - 2 * MARGIN, 300), subtitle, 32, MUTED) + 40
    return y


# ── Slides ──────────────────────────────────────────────────────────────

def cover(p, n, total):
    background(p, BLUE, n, total)
    icon = image(RES / "icon.png")
    p.drawImage(QRectF((W - 300) / 2, 150, 300, 300), icon)
    logo = image(RES / "fmu_manipulation_toolbox.png")
    p.drawImage(QRectF((W - 860) / 2, 500, 860, 860 * logo.height() / logo.width()), logo)
    text(p, QRectF(MARGIN, 700, W - 2 * MARGIN, 120), "Version 2.0", 104, LIGHT["blue"], bold=True,
         align=Qt.AlignmentFlag.AlignHCenter)
    text(p, QRectF(MARGIN + 40, 850, W - 2 * MARGIN - 80, 200),
         "The open-source toolbox to analyse, modify and combine FMUs", 38, TEXT, align=Qt.AlignmentFlag.AlignHCenter)
    chips = ("FMI 2.0 & 3.0", "Python 3.10 – 3.14", "Windows · Linux · macOS")
    p.setFont(font(23, True))
    widths = [QFontMetricsF(p.font()).horizontalAdvance(c) + 44 for c in chips]
    x = (W - sum(widths) - 20 * (len(chips) - 1)) / 2
    for chip, width in zip(chips, widths):
        rect = QRectF(x, 1060, width, 58)
        path = QPainterPath()
        path.addRoundedRect(rect, 29, 29)
        p.fillPath(path, QColor("#4b4e51"))
        p.setPen(TEXT)
        p.setFont(font(23, True))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, chip)
        x += width + 20
    text(p, QRectF(MARGIN, 1160, W - 2 * MARGIN, 60), "What's new  →", 30, MUTED, align=Qt.AlignmentFlag.AlignHCenter)


def tools(p, n, total):
    background(p, BLUE, n, total)
    y = title_block(p, 110, "THE TOOLBOX", BLUE, "Three tools, one toolbox",
                    "Graphical interfaces, command line and Python API, for FMI 2.0 and 3.0 FMUs.")
    entries = (("fmutool.png", "FMU Tool", "summarise, check, rename or remove ports, compile sources, add remoting"),
               ("fmueditor.png", "FMU Editor", "edit names, descriptions and experiment settings"),
               ("fmucontainer.png", "FMU Container Builder", "combine FMUs into one FMU, graphically"))
    for icon, name, what in entries:
        p.drawImage(QRectF(MARGIN, y, 150, 150), image(RES / icon))
        text(p, QRectF(MARGIN + 190, y + 18, W - 2 * MARGIN - 190, 60), name, 38, bold=True)
        text(p, QRectF(MARGIN + 190, y + 72, W - 2 * MARGIN - 190, 120), what, 28, MUTED)
        y += 200
    y += 10
    bullets(p, y, ["CLI: fmutool, fmucontainer, fmusplit", "Python API for your own scripts and checkers"],
            LIGHT["blue"], size=30, spacing=18)


def ai(p, n, total):
    background(p, PURPLE, n, total)
    y = title_block(p, 110, "NEW · AI ASSISTANT", PURPLE, "Let an AI agent build your containers",
                    "An MCP server (Model Context Protocol) exposes the toolbox to GitHub Copilot, Claude, "
                    "VS Code, local models...")
    y = bubble(p, QRectF(MARGIN + 120, y, W - 2 * MARGIN - 120, 0),
               "Add bb_position.fmu and bb_velocity.fmu, link the ports of same name, and save the container.",
               BLUE, "YOU", TEXT) + 26
    y = bubble(p, QRectF(MARGIN, y, W - 2 * MARGIN - 120, 0),
               "Done: 2 FMUs, 1 link (velocity). Saved as bouncing.fmu. Note: the input reset of "
               "bb_velocity.fmu is not fed.",
               PANEL, "AGENT", LIGHT["purple"]) + 50
    bullets(p, y, ["Drives the live Container Builder canvas",
                   "Standalone server: fmutool-mcp, no GUI needed",
                   "Inspects, checks and lints assemblies"], LIGHT["purple"], size=31, spacing=16)


def model_exchange(p, n, total):
    background(p, GREEN, n, total)
    y = title_block(p, 110, "NEW · CONTAINERS", GREEN, "Model-Exchange FMUs inside containers",
                    "An embedded fixed-step solver advances them together, with their state and time events.")
    outer = QRectF(MARGIN, y + 10, W - 2 * MARGIN, 470)
    path = QPainterPath()
    path.addRoundedRect(outer, 30, 30)
    p.setPen(QPen(LIGHT["green"], 4, Qt.PenStyle.DashLine))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    text(p, QRectF(outer.x() + 30, outer.y() + 24, 600, 50), "container.fmu", 30, LIGHT["green"], bold=True,
         family=MONO)
    third = (outer.width() - 4 * 30) / 3
    top = outer.y() + 100
    box(p, QRectF(outer.x() + 30, top, third, 150), "CS FMU", "Co-Simulation", BLUE)
    box(p, QRectF(outer.x() + 60 + third, top, third, 150), "ME FMU", "Model-Exchange", GREEN)
    box(p, QRectF(outer.x() + 90 + 2 * third, top, third, 150), "ME FMU", "Model-Exchange", GREEN)
    box(p, QRectF(outer.x() + 60 + third, top + 200, 2 * third + 30, 130), "Embedded solver",
        "forward Euler · RK4", PANEL)
    y = outer.bottom() + 50
    bullets(p, y, ["Mix Co-Simulation and Model-Exchange FMUs", "Events stay consistent across FMUs"],
            LIGHT["green"], size=31, spacing=16)


def link_assistant(p, n, total):
    background(p, ORANGE, n, total)
    y = title_block(p, 110, "NEW · CONTAINER BUILDER", ORANGE, "Hundreds of ports? Link them by rule",
                    "Same name, prefix / suffix, regular expression, similar names: review the proposals, "
                    "then apply.")
    img = image(DOC / "user-guide/fmucontainer/link-assistant-rules.png")
    screenshot(p, img, QRectF(MARGIN - 30, y, W - 2 * MARGIN + 60, H - y - 200),
               QRectF(0, img.height() * 0.065, img.width() * 0.9, img.height() * 0.645))


def instances(p, n, total):
    background(p, ORANGE, n, total)
    y = title_block(p, 110, "NEW · CONTAINERS", ORANGE, "The same FMU, several times",
                    "Each instance has its own name and its own extraction: model.fmu, model-1.fmu...")
    img = image(DOC / "user-guide/fmucontainer/fmucontainer-instances.png")
    screenshot(p, img, QRectF(MARGIN - 30, y, W - 2 * MARGIN + 60, H - y - 200),
               QRectF(img.width() * 0.02, img.height() * 0.13, img.width() * 0.44, img.height() * 0.66))


def compile_sources(p, n, total):
    background(p, GREEN, n, total)
    y = title_block(p, 110, "NEW · FMU TOOL", GREEN, "No binary for your platform? Compile the sources",
                    "The C sources embedded in the FMU are built with your compiler: one click, or "
                    "fmutool -compile-sources.")
    img = image(DOC / "user-guide/fmutool/fmutool-compile.png")
    # The grid of buttons, then the log of the compilation.
    y = screenshot(p, img, QRectF(MARGIN - 30, y, W - 2 * MARGIN + 60, 400),
                   QRectF(img.width() * 0.134, img.height() * 0.055, img.width() * 0.861, img.height() * 0.19)) + 40
    y = screenshot(p, img, QRectF(MARGIN - 30, y, W - 2 * MARGIN + 60, 400),
                   QRectF(0, img.height() * 0.765, img.width() * 0.46, img.height() * 0.165)) + 50
    bullets(p, y, ["FMI 2.0 and 3.0, C and C++",
                   "Visual Studio, gcc or clang: Windows, Linux, macOS",
                   "Extra options if the compiler asks for them"], LIGHT["green"], size=30, spacing=14)


def robust(p, n, total):
    background(p, RED, n, total)
    y = title_block(p, 110, "UNDER THE HOOD", RED, "Safer edits, stricter checks")
    items = (("In-place edits", "modelDescription.xml is edited, not re-generated: annotations, aliases and "
                                "comments are kept."),
             ("FMI semantic checker", "the rules of FMI 2.0 and 3.0 that the XSD cannot express."),
             ("Refused, not broken", "an operation that would break the FMI standard leaves the FMU unchanged."),
             ("Ready for CI", "fmutool -check exits with status 7 on error."),
             ("Strict containers", "unknown ports and inputs fed twice stop the build."))
    for title, what in items:
        p.fillRect(QRectF(MARGIN, y + 6, 8, 96), LIGHT["red"])
        text(p, QRectF(MARGIN + 34, y, W - 2 * MARGIN - 34, 60), title, 36, bold=True)
        y += 52
        y += text(p, QRectF(MARGIN + 34, y, W - 2 * MARGIN - 34, 200), what, 28, MUTED) + 40


def install(p, n, total):
    background(p, BLUE, n, total)
    y = title_block(p, 110, "PACKAGING", BLUE, "Install only what you need",
                    "Python 3.10 to 3.14. The command line no longer needs the GUI toolkit.")
    code(p, QRectF(MARGIN, y, W - 2 * MARGIN, 4 * 98 + 40), [
        ("pip install fmu-manipulation-toolbox", "command line + Python API"),
        ('pip install "fmu-manipulation-toolbox[gui]"', "+ graphical interfaces"),
        ('pip install "fmu-manipulation-toolbox[mcp]"', "+ AI Assistant"),
        ('pip install "fmu-manipulation-toolbox[all]"', "everything"),
    ])
    bullets(p, y + 4 * 98 + 100, ["Wheels include the native binaries (container, remoting)",
                                  "Source distribution with the C sources, built with CMake"],
            LIGHT["blue"], size=30, spacing=18)


def get_it(p, n, total):
    background(p, GREEN, n, total)
    icon = image(RES / "icon.png")
    p.drawImage(QRectF((W - 240) / 2, 150, 240, 240), icon)
    text(p, QRectF(MARGIN, 440, W - 2 * MARGIN, 200), "Try 2.0 and tell us what you think", 60, bold=True,
         align=Qt.AlignmentFlag.AlignHCenter)
    y = 640
    for label, value in (("Source code", "github.com/grouperenault/fmu_manipulation_toolbox"),
                         ("Documentation", "grouperenault.github.io/fmu_manipulation_toolbox"),
                         ("Package", "pypi.org/project/fmu-manipulation-toolbox")):
        text(p, QRectF(MARGIN, y, W - 2 * MARGIN, 50), label, 28, MUTED, align=Qt.AlignmentFlag.AlignHCenter)
        text(p, QRectF(MARGIN - 20, y + 44, W - 2 * MARGIN + 40, 60), value, 31, LIGHT["green"], bold=True,
             align=Qt.AlignmentFlag.AlignHCenter)
        y += 140
    text(p, QRectF(MARGIN, y + 20, W - 2 * MARGIN, 120), "Open source · issues, ideas and stars welcome", 30,
         TEXT, align=Qt.AlignmentFlag.AlignHCenter)


SLIDES = (cover, tools, ai, model_exchange, link_assistant, instances, compile_sources, robust, install, get_it)


def main():
    parser = argparse.ArgumentParser(description="Make the carousel announcing the FMU Manipulation Toolbox 2.0.")
    parser.add_argument("--out", required=True, type=Path, metavar="DIR",
                        help="directory receiving the PDF, the PNG and the WebP files")
    args = parser.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    app = QGuiApplication(sys.argv[:1])
    pdf = QPdfWriter(str(out / "carousel-fmu-manipulation-toolbox-2.0.pdf"))
    pdf.setResolution(72)
    pdf.setPageLayout(QPageLayout(QPageSize(QSizeF(W, H), QPageSize.Unit.Point), QPageLayout.Orientation.Portrait,
                                  QMarginsF(0, 0, 0, 0)))
    pdf.setTitle("FMU Manipulation Toolbox 2.0")
    pdf_painter = QPainter(pdf)
    pdf_painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    for number, slide in enumerate(SLIDES, start=1):
        if number > 1:
            pdf.newPage()
        slide(pdf_painter, number, len(SLIDES))
        png = QImage(W, H, QImage.Format.Format_ARGB32)
        painter = QPainter(png)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
                               | QPainter.RenderHint.TextAntialiasing)
        slide(painter, number, len(SLIDES))
        painter.end()
        png.save(str(out / f"slide-{number:02}.png"))
        if not png.save(str(out / f"slide-{number:02}.webp"), "WEBP", WEBP_QUALITY):
            raise RuntimeError("the webp image format plugin of Qt is missing")
    pdf_painter.end()
    app.processEvents()
    print(f"{len(SLIDES)} slides written into {out}")


if __name__ == "__main__":
    main()
