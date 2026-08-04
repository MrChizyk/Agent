"""
Генерація PDF-файлів (конспектів, тестів тощо) з тексту, який повертає AI
у Markdown-подібному форматі (**жирний**, ### заголовок, * пункт списку).

Використовує вбудований у проєкт шрифт DejaVu Sans, який підтримує
кирилицю (стандартні шрифти reportlab кирилицю не відображають).
"""
import os
import re
import tempfile

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

FONTS_DIR = os.path.join(os.path.dirname(__file__), "..", "fonts")
FONT_REGULAR_PATH = os.path.join(FONTS_DIR, "DejaVuSans.ttf")
FONT_BOLD_PATH = os.path.join(FONTS_DIR, "DejaVuSans-Bold.ttf")

_fonts_registered = False


def _register_fonts():
    """Реєструє шрифт з кирилицею в reportlab (лише один раз за весь час роботи бота)."""
    global _fonts_registered
    if _fonts_registered:
        return
    pdfmetrics.registerFont(TTFont("DejaVuSans", FONT_REGULAR_PATH))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", FONT_BOLD_PATH))
    _fonts_registered = True


def _build_styles() -> dict:
    return {
        "Title": ParagraphStyle(
            "TitleCustom",
            fontName="DejaVuSans-Bold",
            fontSize=19,
            leading=24,
            spaceAfter=14,
            textColor=colors.HexColor("#1a1a2e"),
        ),
        "H1": ParagraphStyle(
            "H1Custom",
            fontName="DejaVuSans-Bold",
            fontSize=14,
            leading=18,
            spaceBefore=12,
            spaceAfter=6,
            textColor=colors.HexColor("#16213e"),
        ),
        "H2": ParagraphStyle(
            "H2Custom",
            fontName="DejaVuSans-Bold",
            fontSize=12,
            leading=16,
            spaceBefore=8,
            spaceAfter=4,
            textColor=colors.HexColor("#0f3460"),
        ),
        "Body": ParagraphStyle(
            "BodyCustom",
            fontName="DejaVuSans",
            fontSize=10.5,
            leading=15,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#222222"),
        ),
    }


def _inline_markdown(text: str) -> str:
    """Екранує спецсимволи та конвертує **жирний** в теги <b>, які розуміє reportlab."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return text


def _markdown_to_flowables(text: str, styles: dict) -> list:
    """Дуже простий парсер Markdown -> список reportlab flowables (абзаци, списки, лінії)."""
    flowables = []
    bullet_buffer = []

    def flush_bullets():
        if not bullet_buffer:
            return
        items = [
            ListItem(Paragraph(_inline_markdown(b), styles["Body"]), spaceAfter=3)
            for b in bullet_buffer
        ]
        flowables.append(
            ListFlowable(items, bulletType="bullet", start="•", leftIndent=16)
        )
        bullet_buffer.clear()

    for raw_line in text.split("\n"):
        line = raw_line.strip()

        if not line:
            flush_bullets()
            flowables.append(Spacer(1, 6))
            continue

        if line in ("---", "***", "___"):
            flush_bullets()
            flowables.append(
                HRFlowable(
                    width="100%",
                    color=colors.HexColor("#cccccc"),
                    spaceBefore=4,
                    spaceAfter=8,
                )
            )
            continue

        header_match = re.match(r"^(#{1,6})\s*(.+)$", line)
        if header_match:
            flush_bullets()
            level = len(header_match.group(1))
            content = _inline_markdown(header_match.group(2))
            style = styles["H1"] if level <= 2 else styles["H2"]
            flowables.append(Paragraph(content, style))
            continue

        bullet_match = re.match(r"^[*\-]\s+(.+)$", line)
        if bullet_match:
            bullet_buffer.append(bullet_match.group(1))
            continue

        flush_bullets()
        flowables.append(Paragraph(_inline_markdown(line), styles["Body"]))

    flush_bullets()
    return flowables


def create_pdf(title: str, markdown_text: str) -> str:
    """
    Створює охайно оформлений PDF-файл із заголовком та текстом у Markdown-
    подібному форматі. Повертає шлях до тимчасового файлу (видалити після відправки).
    """
    _register_fonts()
    styles = _build_styles()

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp_path = tmp.name
    tmp.close()

    doc = SimpleDocTemplate(
        tmp_path,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    flowables = [
        Paragraph(_inline_markdown(title), styles["Title"]),
        HRFlowable(
            width="100%",
            color=colors.HexColor("#4a4e69"),
            thickness=1,
            spaceAfter=14,
        ),
    ]
    flowables.extend(_markdown_to_flowables(markdown_text, styles))

    doc.build(flowables)
    return tmp_path
