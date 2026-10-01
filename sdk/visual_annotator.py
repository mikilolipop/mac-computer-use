#!/usr/bin/env python3
"""
Set-of-Marks (SoM) Visual Badge Annotator for macOS Computer Use
Injects high-contrast numerical badges [1], [2]... onto interactive elements
in window screenshots to eliminate coordinate guessing and hallucination for VLMs.
"""

import os
from typing import List, Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont

def annotate_screenshot(
    image_path: str,
    elements: List[Dict[str, Any]],
    window_bounds: Optional[Dict[str, Any]] = None,
    output_path: Optional[str] = None
) -> str:
    """
    Annotates a window screenshot with Set-of-Marks (SoM) index badges.
    
    Args:
        image_path: Path to the clean screenshot PNG
        elements: List of parsed interactive elements with 'index' and 'bounds'
        window_bounds: Optional bounding box of the window in desktop coordinates {'x', 'y', 'width', 'height'}
        output_path: Optional output file path. Defaults to <image_path>_annotated.png
        
    Returns:
        Path to the annotated image.
    """
    if not os.path.exists(image_path) or not elements:
        return image_path

    try:
        with Image.open(image_path) as orig_img:
            img = orig_img.convert("RGBA")
    except Exception as e:
        return image_path

    draw = ImageDraw.Draw(img)
    img_w, img_h = img.size

    win_x = 0.0
    win_y = 0.0
    win_w = float(img_w)
    win_h = float(img_h)

    import math
    if window_bounds:
        try:
            bx = float(window_bounds.get("x", 0.0))
            by = float(window_bounds.get("y", 0.0))
            bw = float(window_bounds.get("width") or img_w)
            bh = float(window_bounds.get("height") or img_h)
            if math.isfinite(bx) and math.isfinite(by) and math.isfinite(bw) and math.isfinite(bh) and bw > 0 and bh > 0:
                win_x, win_y, win_w, win_h = bx, by, bw, bh
        except (ValueError, TypeError):
            pass

    scale_x = img_w / win_w if win_w > 0 else 1.0
    scale_y = img_h / win_h if win_h > 0 else 1.0

    font_size = max(11, int(13 * scale_x))
    font = None
    # Attempt to load native macOS font
    for font_path in [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf"
    ]:
        if os.path.exists(font_path):
            try:
                font = ImageFont.truetype(font_path, font_size)
                break
            except Exception:
                continue

    if font is None:
        font = ImageFont.load_default()

    for elem in elements:
        bounds = elem.get("bounds")
        idx = elem.get("index")
        if not bounds or idx is None:
            continue

        try:
            ex = float(bounds.get("x", 0.0))
            ey = float(bounds.get("y", 0.0))
            ew = float(bounds.get("width", 0.0))
            eh = float(bounds.get("height", 0.0))
            if not (math.isfinite(ex) and math.isfinite(ey) and math.isfinite(ew) and math.isfinite(eh)):
                continue
        except (ValueError, TypeError):
            continue

        if ew <= 0 or eh <= 0:
            continue

        rel_x = (ex - win_x) * scale_x
        rel_y = (ey - win_y) * scale_y
        rel_w = ew * scale_x
        rel_h = eh * scale_y

        # Skip elements that fall entirely outside the window
        if rel_x + rel_w < 0 or rel_y + rel_h < 0 or rel_x > img_w or rel_y > img_h:
            continue

        # Draw subtle neon outline around element
        outline_color = (0, 140, 255, 170)
        draw.rectangle(
            [rel_x, rel_y, rel_x + rel_w, rel_y + rel_h],
            outline=outline_color,
            width=max(1, int(1.5 * scale_x))
        )

        badge_text = str(idx)
        try:
            bbox = draw.textbbox((0, 0), badge_text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
        except AttributeError:
            text_w = 8 * len(badge_text) * scale_x
            text_h = 12 * scale_y

        pad_x = 4 * scale_x
        pad_y = 2 * scale_y
        badge_w = text_w + pad_x * 2
        badge_h = text_h + pad_y * 2

        # Position badge at top-left corner inside the element (or clamped inside)
        badge_x = max(rel_x, 2.0)
        badge_y = max(rel_y, 2.0)

        pill_box = [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h]
        # High contrast crimson badge with white border
        draw.rounded_rectangle(
            pill_box,
            radius=max(2, int(3 * scale_x)),
            fill=(220, 38, 38, 235),
            outline=(255, 255, 255, 240),
            width=max(1, int(1 * scale_x))
        )

        # Draw centered crisp white index text
        draw.text(
            (badge_x + pad_x, badge_y + pad_y - 1),
            badge_text,
            font=font,
            fill=(255, 255, 255, 255)
        )

    if not output_path:
        base, ext = os.path.splitext(image_path)
        output_path = f"{base}_annotated{ext}"

    img.save(output_path, "PNG")
    return output_path
