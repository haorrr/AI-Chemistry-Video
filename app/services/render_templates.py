"""Per-visual-type Pillow slide drawing. Pure rendering logic, no MoviePy/video
concerns — kept separate from video_renderer.py per the file-size split rule."""

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.models import Scene

SLIDE_SIZE = (1280, 720)
MARGIN = 60
HEADING_FONT_SIZE = 48
BODY_FONT_SIZE = 32
HEADING_BAR_HEIGHT = 100

BG_COLOR = (250, 250, 250)
TEXT_COLOR = (20, 20, 20)
HEADING_BAR_COLOR = (30, 60, 120)
HEADING_TEXT_COLOR = (255, 255, 255)

# Bundled font is preferred (cross-platform, deterministic) but not currently
# vendored in this repo — kept first so dropping a real TTF here later "just
# works" with no code change. Falls through to well-known OS font paths;
# raises loudly rather than silently degrading to PIL's unreadable default
# bitmap font (explicit project requirement — readability over silent fallback).
_FONT_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "assets" / "fonts" / "DejaVuSans.ttf",
    Path(r"C:\Windows\Fonts\segoeui.ttf"),
    Path(r"C:\Windows\Fonts\arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
]


@lru_cache(maxsize=1)
def _resolve_font_path() -> Path:
    for candidate in _FONT_CANDIDATES:
        if candidate.exists():
            return candidate
    raise RuntimeError(
        "No usable TTF font found (checked bundled app/assets/fonts/ and common "
        "OS font paths). Refusing to silently fall back to PIL's unreadable "
        "default bitmap font — install a TTF font or vendor one into "
        "app/assets/fonts/."
    )


@lru_cache(maxsize=None)
def _load_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_resolve_font_path()), size)


def _text_line_height(font: ImageFont.FreeTypeFont) -> int:
    return int(font.size * 1.4)


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
                max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        width = bbox[2] - bbox[0]
        if width <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_centered_lines(draw: ImageDraw.ImageDraw, lines: list[str],
                          font: ImageFont.FreeTypeFont, center_x: float, start_y: float,
                          color: tuple) -> float:
    line_h = _text_line_height(font)
    y = start_y
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        draw.text((center_x - w / 2, y), line, font=font, fill=color)
        y += line_h
    return y


def _draw_left_lines(draw: ImageDraw.ImageDraw, lines: list[str],
                      font: ImageFont.FreeTypeFont, x: float, start_y: float,
                      color: tuple) -> float:
    line_h = _text_line_height(font)
    y = start_y
    for line in lines:
        draw.text((x, y), line, font=font, fill=color)
        y += line_h
    return y


def _draw_heading_bar(draw: ImageDraw.ImageDraw, heading: str, size: tuple[int, int]) -> None:
    draw.rectangle([(0, 0), (size[0], HEADING_BAR_HEIGHT)], fill=HEADING_BAR_COLOR)
    font = _load_font(HEADING_FONT_SIZE)
    max_width = size[0] - 2 * MARGIN
    lines = _wrap_text(draw, heading, font, max_width)[:2]
    line_h = _text_line_height(font)
    total_h = len(lines) * line_h
    y = (HEADING_BAR_HEIGHT - total_h) / 2
    _draw_centered_lines(draw, lines, font, size[0] / 2, y, HEADING_TEXT_COLOR)


def _draw_title_body(draw: ImageDraw.ImageDraw, scene: Scene, size: tuple[int, int]) -> None:
    font_heading = _load_font(HEADING_FONT_SIZE + 12)
    font_body = _load_font(BODY_FONT_SIZE + 4)
    max_width = size[0] - 2 * MARGIN

    heading_lines = _wrap_text(draw, scene.heading, font_heading, max_width)
    body_lines = _wrap_text(draw, scene.visual_text, font_body, max_width)

    line_h_heading = _text_line_height(font_heading)
    line_h_body = _text_line_height(font_body)
    total_height = (
        len(heading_lines) * line_h_heading + line_h_body + len(body_lines) * line_h_body
    )

    y = (size[1] - total_height) / 2
    y = _draw_centered_lines(draw, heading_lines, font_heading, size[0] / 2, y, TEXT_COLOR)
    y += line_h_body / 2
    _draw_centered_lines(draw, body_lines, font_body, size[0] / 2, y, TEXT_COLOR)


def _is_logarithmic_scene(scene: Scene) -> bool:
    return "logarithmic" in scene.heading.lower()


def _draw_ph_bar(draw: ImageDraw.ImageDraw, box: tuple, bar_y0: float) -> float:
    """Draws the 0-14 acidic/neutral/basic bar + labels. Returns the y just below it."""
    x0, _, x1, _ = box
    bar_y1 = bar_y0 + 60
    mid_x = x0 + (x1 - x0) // 2

    draw.rectangle([(x0, bar_y0), (mid_x, bar_y1)], fill=(200, 50, 50))
    draw.rectangle([(mid_x, bar_y0), (x1, bar_y1)], fill=(50, 90, 200))
    draw.rectangle([(mid_x - 4, bar_y0), (mid_x + 4, bar_y1)], fill=(50, 160, 70))

    label_font = _load_font(BODY_FONT_SIZE - 4)
    _draw_centered_lines(draw, ["0", "Acidic"], label_font, x0 + 60, bar_y1 + 10, TEXT_COLOR)
    _draw_centered_lines(draw, ["7", "Neutral"], label_font, mid_x, bar_y1 + 10, TEXT_COLOR)
    _draw_centered_lines(draw, ["14", "Basic"], label_font, x1 - 60, bar_y1 + 10, TEXT_COLOR)
    return bar_y1 + 10 + _text_line_height(label_font) * 2


def _draw_concentration_chart(draw: ImageDraw.ImageDraw, box: tuple, top_y: float) -> None:
    """Visualizes the logarithmic H+ concentration relationship: pH 5/4/3 with
    increasing (capped, illustrative-not-literal) dot clusters and explicit
    x1/x10/x100 labels doing the precise communication."""
    x0, _, x1, y1 = box
    col_width = (x1 - x0) // 3
    ph_labels = ["pH 5", "pH 4", "pH 3"]
    dot_counts = [1, 4, 9]
    multiplier_labels = ["×1", "×10", "×100"]
    label_font = _load_font(BODY_FONT_SIZE - 6)
    dot_r = 7
    spacing = 20

    for i in range(3):
        cx = x0 + col_width * i + col_width // 2
        y = _draw_centered_lines(draw, [ph_labels[i]], label_font, cx, top_y, TEXT_COLOR)
        n = dot_counts[i]
        cols = 3
        rows = (n + cols - 1) // cols
        dots_top = y + 15
        for d in range(n):
            row, col = divmod(d, cols)
            row_items = min(cols, n - row * cols)
            row_x0 = cx - (row_items * spacing) // 2
            dx = row_x0 + col * spacing
            dy = dots_top + row * spacing
            draw.ellipse([(dx - dot_r, dy - dot_r), (dx + dot_r, dy + dot_r)], fill=(200, 50, 50))
        _draw_centered_lines(
            draw, [multiplier_labels[i]], label_font, cx,
            min(dots_top + rows * spacing + 10, y1 - _text_line_height(label_font)), TEXT_COLOR
        )


def _draw_ph_scale_body(draw: ImageDraw.ImageDraw, scene: Scene, box: tuple) -> None:
    x0, y0, x1, y1 = box

    if _is_logarithmic_scene(scene):
        # Bar near the top, concentration chart fills the remaining space below —
        # the chart carries the "why logarithmic" content, so no redundant caption.
        bottom = _draw_ph_bar(draw, box, y0 + 20)
        _draw_concentration_chart(draw, box, bottom + 20)
    else:
        # Zone scene: the bar + labels already say everything scene.visual_text
        # would restate in prose, so skip the redundant caption and instead
        # vertically center the diagram to use the available space.
        diagram_height = 60 + 10 + _text_line_height(_load_font(BODY_FONT_SIZE - 4)) * 2
        bar_y0 = y0 + max(0, ((y1 - y0) - diagram_height) // 2)
        _draw_ph_bar(draw, box, bar_y0)


def _is_transfer_scene(scene: Scene) -> bool:
    return "transfer" in scene.heading.lower()


def _extract_atom_labels(scene: Scene) -> tuple[str, str]:
    """Deterministic keyword match against this project's fixed set of authored
    storyboard templates (same pattern as _is_transfer_scene) — not a general
    chemistry-text parser."""
    text = scene.visual_text
    if "Na" in text and "Cl" in text:
        return ("Na⁺", "Cl⁻") if _is_transfer_scene(scene) else ("Na", "Cl")
    if "Atom A" in text and "Atom B" in text:
        return "A", "B"
    return "H", "H"


def _draw_atom_sharing_body(draw: ImageDraw.ImageDraw, scene: Scene, box: tuple) -> None:
    x0, y0, x1, y1 = box
    center_y = y0 + (y1 - y0) // 3
    r = 60
    left_cx = x0 + (x1 - x0) // 3
    right_cx = x1 - (x1 - x0) // 3

    draw.ellipse([(left_cx - r, center_y - r), (left_cx + r, center_y + r)],
                 outline=(60, 110, 200), width=6)
    draw.ellipse([(right_cx - r, center_y - r), (right_cx + r, center_y + r)],
                 outline=(200, 90, 60), width=6)

    left_label, right_label = _extract_atom_labels(scene)
    atom_font = _load_font(BODY_FONT_SIZE)
    for cx, label in ((left_cx, left_label), (right_cx, right_label)):
        bbox = draw.textbbox((0, 0), label, font=atom_font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((cx - w / 2, center_y - h / 2 - bbox[1]), label, font=atom_font, fill=TEXT_COLOR)

    mid_x = (left_cx + right_cx) // 2
    if _is_transfer_scene(scene):
        arrow_y = center_y
        draw.line([(left_cx + r + 10, arrow_y), (right_cx - r - 20, arrow_y)],
                  fill=(30, 30, 30), width=6)
        draw.polygon([
            (right_cx - r - 20, arrow_y - 15),
            (right_cx - r - 20, arrow_y + 15),
            (right_cx - r, arrow_y),
        ], fill=(30, 30, 30))
        # Electron dot partway along the transfer arrow — distinct from the arrow
        # itself, makes it read as "an electron moving" not just "an arrow".
        electron_x = left_cx + r + 10 + int((right_cx - r - 20 - (left_cx + r + 10)) * 0.4)
        electron_r = 9
        draw.ellipse(
            [(electron_x - electron_r, arrow_y - electron_r),
             (electron_x + electron_r, arrow_y + electron_r)],
            fill=(230, 180, 30), outline=(30, 30, 30), width=2,
        )
        label = "electron transfer"
    else:
        draw.ellipse([(mid_x - 14, center_y - 6), (mid_x - 2, center_y + 6)], fill=(30, 30, 30))
        draw.ellipse([(mid_x + 2, center_y - 6), (mid_x + 14, center_y + 6)], fill=(30, 30, 30))
        label = "shared electron pair"

    label_font = _load_font(BODY_FONT_SIZE - 4)
    y = _draw_centered_lines(draw, [label], label_font, mid_x, center_y + r + 20, TEXT_COLOR)

    body_font = _load_font(BODY_FONT_SIZE)
    lines = _wrap_text(draw, scene.visual_text, body_font, x1 - x0)
    _draw_left_lines(draw, lines, body_font, x0, y + 30, TEXT_COLOR)


def _draw_comparison_table_body(draw: ImageDraw.ImageDraw, scene: Scene, box: tuple) -> None:
    x0, y0, x1, y1 = box
    columns = [c.strip() for c in scene.visual_text.split("|")]
    if len(columns) < 2:
        columns = [scene.visual_text, ""]
    col_width = (x1 - x0) // len(columns)
    row_top = y0 + 20
    row_bottom = y1 - 100

    for i in range(len(columns) + 1):
        cx = x0 + i * col_width
        draw.line([(cx, row_top), (cx, row_bottom)], fill=(120, 120, 120), width=3)
    draw.line([(x0, row_top), (x0 + col_width * len(columns), row_top)],
              fill=(120, 120, 120), width=3)
    draw.line([(x0, row_bottom), (x0 + col_width * len(columns), row_bottom)],
              fill=(120, 120, 120), width=3)

    body_font = _load_font(BODY_FONT_SIZE - 4)
    for i, col_text in enumerate(columns):
        cx0 = x0 + i * col_width + 20
        lines = _wrap_text(draw, col_text, body_font, col_width - 40)
        _draw_left_lines(draw, lines, body_font, cx0, row_top + 20, TEXT_COLOR)


_SUMMARY_CATEGORY_COLORS = {
    "acidic": (200, 50, 50),
    "neutral": (50, 160, 70),
    "basic": (50, 90, 200),
}


def _summary_item_color(item: str) -> tuple:
    lowered = item.lower()
    for keyword, color in _SUMMARY_CATEGORY_COLORS.items():
        if keyword in lowered:
            return color
    return (90, 90, 90)


def _draw_summary_cards(draw: ImageDraw.ImageDraw, items: list[str], box: tuple) -> None:
    """Short (2-3 item) lists render as horizontal colour-coded badge cards,
    vertically centered — used for e.g. the pH scale's acidic/neutral/basic
    examples, reusing the same colour scheme as the pH bar for consistency."""
    x0, y0, x1, y1 = box
    n = len(items)
    col_width = (x1 - x0) // n
    badge_r = 55
    center_y = y0 + (y1 - y0) // 2 - 20
    label_font = _load_font(BODY_FONT_SIZE - 2)

    for i, item in enumerate(items):
        cx = x0 + col_width * i + col_width // 2
        draw.ellipse(
            [(cx - badge_r, center_y - badge_r), (cx + badge_r, center_y + badge_r)],
            fill=_summary_item_color(item),
        )
        lines = _wrap_text(draw, item, label_font, col_width - 40)
        _draw_centered_lines(draw, lines, label_font, cx, center_y + badge_r + 20, TEXT_COLOR)


def _draw_summary_bullets(draw: ImageDraw.ImageDraw, items: list[str], box: tuple,
                           body_font: ImageFont.FreeTypeFont) -> None:
    """Longer/prose-style items render as a vertically-centered bullet list
    (not top-left anchored, to avoid wasting the lower half of the slide)."""
    x0, y0, x1, y1 = box
    bullet_max_width = (x1 - x0) - 40
    line_h = _text_line_height(body_font)
    item_lines = [_wrap_text(draw, f"• {item}", body_font, bullet_max_width) for item in items]
    total_lines = sum(len(lines) for lines in item_lines)
    total_height = total_lines * line_h + (len(item_lines) - 1) * (line_h * 0.4)

    y = y0 + max(0, ((y1 - y0) - total_height) / 2)
    for lines in item_lines:
        y = _draw_left_lines(draw, lines, body_font, x0 + 20, y, TEXT_COLOR)
        y += line_h * 0.4


def _draw_summary_body(draw: ImageDraw.ImageDraw, scene: Scene, box: tuple) -> None:
    items = [s.strip() for s in scene.visual_text.split(".") if s.strip()]
    body_font = _load_font(BODY_FONT_SIZE)

    is_short_list = len(items) in (2, 3) and all(len(item) <= 30 for item in items)
    if is_short_list:
        _draw_summary_cards(draw, items, box)
    else:
        _draw_summary_bullets(draw, items, box, body_font)


def draw_slide(scene: Scene, size: tuple[int, int] = SLIDE_SIZE) -> Image.Image:
    img = Image.new("RGB", size, color=BG_COLOR)
    draw = ImageDraw.Draw(img)

    if scene.visual_type == "title":
        _draw_title_body(draw, scene, size)
        return img

    _draw_heading_bar(draw, scene.heading, size)
    body_box = (MARGIN, HEADING_BAR_HEIGHT + MARGIN, size[0] - MARGIN, size[1] - MARGIN)

    if scene.visual_type == "ph_scale":
        _draw_ph_scale_body(draw, scene, body_box)
    elif scene.visual_type == "atom_sharing":
        _draw_atom_sharing_body(draw, scene, body_box)
    elif scene.visual_type == "comparison_table":
        _draw_comparison_table_body(draw, scene, body_box)
    elif scene.visual_type == "summary":
        _draw_summary_body(draw, scene, body_box)
    else:
        raise ValueError(f"Unsupported visual_type: {scene.visual_type}")

    return img
