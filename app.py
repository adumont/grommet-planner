# Grommet Strip Planner
# Copyright (C) 2023 Alexandre Dumont <adumont@gmail.com>
# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import dataclass
import io
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

RL_pagesizes: Any = None
RL_units: Any = None
RL_canvas_module: Any = None

try:
    import reportlab.lib.pagesizes as RL_pagesizes
    import reportlab.lib.units as RL_units
    import reportlab.pdfgen.canvas as RL_canvas_module

    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False


MM_PER_INCH = 25.4
APP_URL = "https://grommet-planner.streamlit.app/"
MODE_GROMMETS = "Grommets"
MODE_BUTTONHOLES = "Buttonholes"


def _planner_terms(planner_mode: str) -> dict[str, str]:
    if planner_mode == MODE_BUTTONHOLES:
        return {
            "item_singular": "buttonhole",
            "item_plural": "buttonholes",
            "line": "Bust",
            "line_lower": "bust",
            "line_title": "bust line",
            "size_label": "Buttonhole length",
            "app_title": "Buttonhole Strip Planner",
            "app_subtitle": "Plan evenly spaced buttonholes on a strip with end margins.",
        }

    return {
        "item_singular": "grommet",
        "item_plural": "grommets",
        "line": "Waist",
        "line_lower": "waist",
        "line_title": "waist",
        "size_label": "Grommet external diameter",
        "app_title": "Grommet Strip Planner",
        "app_subtitle": "Plan evenly spaced grommet centers on a strip with end margins.",
    }


def _buttonhole_dimensions(
    feature_length_mm: float, scale_factor: float, flip_90: bool
) -> tuple[float, float]:
    long_side = max(1e-6, feature_length_mm) * scale_factor
    short_side = max(0.6 * scale_factor, long_side / 10)
    if flip_90:
        return short_side, long_side
    return long_side, short_side


def _buttonhole_is_flipped(
    index: int, total: int, flip_all_90: bool, flip_last_90: bool
) -> bool:
    if flip_all_90:
        return True
    return flip_last_90 and total > 0 and index == (total - 1)


def _buttonhole_half_extent_mm(feature_length_mm: float, flipped_90: bool) -> float:
    width_mm, _ = _buttonhole_dimensions(feature_length_mm, 1.0, flipped_90)
    return width_mm / 2


@dataclass
class GrommetLayout:
    centers_mm: list[float]
    center_spacings_mm: list[float]
    edge_gaps_mm: list[float]
    uniform_center_spacing_mm: float | None
    start_center_mm: float
    end_center_mm: float
    waist_position_mm: float
    waist_pair_indices: tuple[int, int] | None
    warnings: list[str]


def _build_spacing_lists(
    centers_mm: list[float],
    radius_mm: float,
    feature_half_sizes_mm: list[float] | None = None,
) -> tuple[list[float], list[float], float | None]:
    center_spacings = [
        centers_mm[i + 1] - centers_mm[i] for i in range(len(centers_mm) - 1)
    ]
    if feature_half_sizes_mm is not None and len(feature_half_sizes_mm) == len(
        centers_mm
    ):
        edge_gaps = [
            center_spacings[i]
            - (feature_half_sizes_mm[i] + feature_half_sizes_mm[i + 1])
            for i in range(len(center_spacings))
        ]
    else:
        edge_gaps = [spacing - (2 * radius_mm) for spacing in center_spacings]

    if not center_spacings:
        return center_spacings, edge_gaps, None

    first_spacing = center_spacings[0]
    is_uniform = all(abs(spacing - first_spacing) < 1e-9 for spacing in center_spacings)
    return center_spacings, edge_gaps, (first_spacing if is_uniform else None)


def _find_standard_pair_index(
    layout: GrommetLayout, use_closer_waist_pair: bool
) -> int | None:
    if len(layout.centers_mm) < 2:
        return None

    for pair_index in range(len(layout.centers_mm) - 1):
        is_waist_pair = (
            use_closer_waist_pair
            and layout.waist_pair_indices is not None
            and layout.waist_pair_indices[0]
            <= pair_index
            < layout.waist_pair_indices[1]
        )
        if not is_waist_pair:
            return pair_index
    return None


def _letter_landscape_layout(
    length_mm: float,
) -> tuple[float, float, float, float, int]:
    page_w = 279.4
    page_h = 215.9
    margin_mm = 10.0
    usable_w = page_w - (2 * margin_mm)
    page_count = max(1, int(-(-length_mm // usable_w)))
    return page_w, page_h, margin_mm, usable_w, page_count


def build_printable_svg_letter(
    length_mm: float,
    margin_top_mm: float,
    margin_bottom_mm: float,
    radius_mm: float,
    layout: GrommetLayout,
    use_closer_waist_pair: bool,
    count: int,
    waist_edge_gap_mm: float,
    planner_mode: str,
    item_plural: str,
    line_label: str,
    buttonhole_flip_90: bool,
    buttonhole_flip_last_90: bool,
) -> tuple[str, float, str]:
    page_margin = 10.0
    page_w = length_mm + (2 * page_margin)
    page_h = 160.0
    scale = 1.0
    start_x = page_margin
    orientation = "Full-width SVG"
    strip_y = 28.0
    strip_h = max(18.0, (2 * radius_mm * scale) + 8.0)
    center_y = strip_y + (strip_h / 2)

    def x_pos(value_mm: float) -> float:
        return start_x + value_mm * scale

    def fmt_both(value_mm: float) -> str:
        return f"{value_mm:.2f} mm ({value_mm / MM_PER_INCH:.3f} in)"

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{page_w}mm" height="{page_h}mm" viewBox="0 0 {page_w} {page_h}">',
        f'<rect x="0.5" y="0.5" width="{page_w - 1}" height="{page_h - 1}" fill="white" stroke="#d4d4d8" stroke-width="0.5"/>',
        f'<text x="{page_margin}" y="10" font-size="6" fill="#18181b">{item_plural[:-1].capitalize()} template (full scale SVG)</text>',
        f'<text x="{page_margin}" y="16" font-size="5" fill="#18181b">Print setting: Actual size / 100%. Drawing scale: {scale * 100:.2f}%</text>',
        f'<rect x="{x_pos(0)}" y="{strip_y}" width="{length_mm * scale}" height="{strip_h}" fill="#ffffff" stroke="#111827" stroke-width="0.6"/>',
        f'<line x1="{x_pos(0)}" y1="{strip_y + strip_h + 6}" x2="{x_pos(length_mm)}" y2="{strip_y + strip_h + 6}" stroke="#111827" stroke-width="0.4"/>',
        f'<text x="{(x_pos(0) + x_pos(length_mm)) / 2}" y="{strip_y + strip_h + 11}" text-anchor="middle" font-size="4.5" fill="#111827">Total length: {fmt_both(length_mm)}</text>',
        f'<line x1="{x_pos(0)}" y1="{strip_y - 5}" x2="{x_pos(margin_top_mm)}" y2="{strip_y - 5}" stroke="#0369a1" stroke-width="0.5"/>',
        f'<line x1="{x_pos(length_mm - margin_bottom_mm)}" y1="{strip_y - 5}" x2="{x_pos(length_mm)}" y2="{strip_y - 5}" stroke="#0369a1" stroke-width="0.5"/>',
        f'<text x="{(x_pos(0) + x_pos(margin_top_mm)) / 2}" y="{strip_y - 7}" text-anchor="middle" font-size="3.5" fill="#0369a1">Top: {fmt_both(margin_top_mm)}</text>',
        f'<text x="{(x_pos(length_mm - margin_bottom_mm) + x_pos(length_mm)) / 2}" y="{strip_y - 7}" text-anchor="middle" font-size="3.5" fill="#0369a1">Bottom: {fmt_both(margin_bottom_mm)}</text>',
    ]

    waist_left = waist_right = None
    if layout.waist_pair_indices is not None and layout.waist_pair_indices[1] < len(
        layout.centers_mm
    ):
        waist_left = layout.centers_mm[layout.waist_pair_indices[0]]
        waist_right = layout.centers_mm[layout.waist_pair_indices[1]]

    for index, center in enumerate(layout.centers_mm):
        is_waist = (
            use_closer_waist_pair
            and layout.waist_pair_indices is not None
            and layout.waist_pair_indices[0] <= index <= layout.waist_pair_indices[1]
        )
        stroke = "#c2410c" if is_waist else "#1f2937"
        fill = "#fff7ed" if is_waist else "#ffffff"
        if planner_mode == MODE_BUTTONHOLES:
            flipped_90 = _buttonhole_is_flipped(
                index=index,
                total=len(layout.centers_mm),
                flip_all_90=buttonhole_flip_90,
                flip_last_90=(buttonhole_flip_last_90 and (not buttonhole_flip_90)),
            )
            rect_w, rect_h = _buttonhole_dimensions(2 * radius_mm, scale, flipped_90)
            shape = f'<rect x="{x_pos(center) - (rect_w / 2)}" y="{center_y - (rect_h / 2)}" width="{rect_w}" height="{rect_h}" rx="0.8" fill="{fill}" stroke="{stroke}" stroke-width="0.5"/>'
        else:
            shape = f'<circle cx="{x_pos(center)}" cy="{center_y}" r="{max(0.8, radius_mm * scale)}" fill="{fill}" stroke="{stroke}" stroke-width="0.5"/>'
        svg.extend(
            [
                shape,
                f'<line x1="{x_pos(center)}" y1="{strip_y - 1}" x2="{x_pos(center)}" y2="{strip_y + strip_h + 1}" stroke="{stroke}" stroke-width="0.35" stroke-dasharray="1.2 1.2"/>',
            ]
        )

    svg.append(
        f'<line x1="{x_pos(0)}" y1="{center_y}" x2="{x_pos(length_mm)}" y2="{center_y}" stroke="#1f2937" stroke-width="0.35" stroke-dasharray="1.2 1.2"/>'
    )

    waist_x = layout.waist_position_mm
    if 0 <= waist_x <= length_mm:
        svg.extend(
            [
                f'<line x1="{x_pos(waist_x)}" y1="{strip_y - 7}" x2="{x_pos(waist_x)}" y2="{strip_y + strip_h + 7}" stroke="#b91c1c" stroke-width="0.45" stroke-dasharray="1.5 1.5"/>',
                f'<text x="{x_pos(waist_x)}" y="{strip_y + strip_h + 18}" text-anchor="middle" font-size="4.3" fill="#b91c1c">{line_label}: {fmt_both(waist_x)}</text>',
            ]
        )

    standard_pair_index = _find_standard_pair_index(layout, use_closer_waist_pair)
    if standard_pair_index is not None:
        c1 = layout.centers_mm[standard_pair_index]
        c2 = layout.centers_mm[standard_pair_index + 1]
        c2c = c2 - c1
        edge_gap = c2c - (2 * radius_mm)
        y_c2c = strip_y + strip_h + 24
        y_gap = strip_y + strip_h + 34
        svg.extend(
            [
                f'<line x1="{x_pos(c1)}" y1="{y_c2c}" x2="{x_pos(c2)}" y2="{y_c2c}" stroke="#166534" stroke-width="0.55"/>',
                f'<line x1="{x_pos(c1)}" y1="{y_c2c - 2}" x2="{x_pos(c1)}" y2="{y_c2c + 2}" stroke="#166534" stroke-width="0.4"/>',
                f'<line x1="{x_pos(c2)}" y1="{y_c2c - 2}" x2="{x_pos(c2)}" y2="{y_c2c + 2}" stroke="#166534" stroke-width="0.4"/>',
                f'<text x="{(x_pos(c1) + x_pos(c2)) / 2}" y="{y_c2c - 3}" text-anchor="middle" font-size="4.2" fill="#166534">Standard center-to-center: {fmt_both(c2c)}</text>',
                f'<line x1="{x_pos(c1 + radius_mm)}" y1="{y_gap}" x2="{x_pos(c2 - radius_mm)}" y2="{y_gap}" stroke="#0f766e" stroke-width="0.55"/>',
                f'<line x1="{x_pos(c1 + radius_mm)}" y1="{y_gap - 2}" x2="{x_pos(c1 + radius_mm)}" y2="{y_gap + 2}" stroke="#0f766e" stroke-width="0.4"/>',
                f'<line x1="{x_pos(c2 - radius_mm)}" y1="{y_gap - 2}" x2="{x_pos(c2 - radius_mm)}" y2="{y_gap + 2}" stroke="#0f766e" stroke-width="0.4"/>',
                f'<text x="{(x_pos(c1) + x_pos(c2)) / 2}" y="{y_gap - 3}" text-anchor="middle" font-size="4.2" fill="#0f766e">Standard edge gap: {fmt_both(edge_gap)}</text>',
            ]
        )

    if use_closer_waist_pair and layout.waist_pair_indices is not None:
        waist_start_index = layout.waist_pair_indices[0]
        waist_end_index = layout.waist_pair_indices[1]
        if waist_end_index > waist_start_index and waist_end_index < len(
            layout.centers_mm
        ):
            waist_left = layout.centers_mm[waist_start_index]
            waist_right = layout.centers_mm[waist_start_index + 1]
        else:
            waist_left = waist_right = None

    if use_closer_waist_pair and waist_left is not None and waist_right is not None:
        waist_c2c = waist_right - waist_left
        y_waist_top = strip_y + 5
        y_waist_gap = strip_y + strip_h + 44
        svg.extend(
            [
                f'<line x1="{x_pos(waist_left)}" y1="{y_waist_top}" x2="{x_pos(waist_right)}" y2="{y_waist_top}" stroke="#b45309" stroke-width="0.55"/>',
                f'<line x1="{x_pos(waist_left)}" y1="{y_waist_top - 2}" x2="{x_pos(waist_left)}" y2="{y_waist_top + 2}" stroke="#b45309" stroke-width="0.4"/>',
                f'<line x1="{x_pos(waist_right)}" y1="{y_waist_top - 2}" x2="{x_pos(waist_right)}" y2="{y_waist_top + 2}" stroke="#b45309" stroke-width="0.4"/>',
                f'<text x="{(x_pos(waist_left) + x_pos(waist_right)) / 2}" y="{y_waist_top - 3}" text-anchor="middle" font-size="4.2" fill="#92400e">{line_label} center-to-center: {fmt_both(waist_c2c)}</text>',
                f'<line x1="{x_pos(waist_left + radius_mm)}" y1="{y_waist_gap}" x2="{x_pos(waist_right - radius_mm)}" y2="{y_waist_gap}" stroke="#ea580c" stroke-width="0.55"/>',
                f'<line x1="{x_pos(waist_left + radius_mm)}" y1="{y_waist_gap - 2}" x2="{x_pos(waist_left + radius_mm)}" y2="{y_waist_gap + 2}" stroke="#ea580c" stroke-width="0.4"/>',
                f'<line x1="{x_pos(waist_right - radius_mm)}" y1="{y_waist_gap - 2}" x2="{x_pos(waist_right - radius_mm)}" y2="{y_waist_gap + 2}" stroke="#ea580c" stroke-width="0.4"/>',
                f'<text x="{(x_pos(waist_left) + x_pos(waist_right)) / 2}" y="{y_waist_gap - 3}" text-anchor="middle" font-size="4.2" fill="#9a3412">{line_label} edge gap: {fmt_both(waist_c2c - (2 * radius_mm))}</text>',
            ]
        )

    centers_text = [
        f"{idx + 1}:{value:.2f}mm/{value / MM_PER_INCH:.3f}in"
        for idx, value in enumerate(layout.centers_mm)
    ]
    chunk_size = 10
    base_y = strip_y + strip_h + 58
    for line_index in range(0, len(centers_text), chunk_size):
        chunk = centers_text[line_index : line_index + chunk_size]
        svg.append(
            f'<text x="{page_margin}" y="{base_y + (line_index // chunk_size) * 6}" font-size="4.1" fill="#18181b">Centers (mm/in) {", ".join(chunk)}</text>'
        )

    param_y = 130.0
    waist_n = (
        (layout.waist_pair_indices[1] - layout.waist_pair_indices[0] + 1)
        if (use_closer_waist_pair and layout.waist_pair_indices is not None)
        else 2
    )
    waist_info = (
        f"  |  Count: {waist_n}  |  {line_label} at: {fmt_both(layout.waist_position_mm)}  |  {line_label} edge gap: {fmt_both(waist_edge_gap_mm)}"
        if use_closer_waist_pair
        else ""
    )
    feature_size_label = "Length" if planner_mode == MODE_BUTTONHOLES else "Diameter"
    param_line1 = f"Strip length: {fmt_both(length_mm)}   |   Top margin: {fmt_both(margin_top_mm)}   |   Bottom margin: {fmt_both(margin_bottom_mm)}   |   {feature_size_label}: {fmt_both(radius_mm * 2)}   |   {item_plural.capitalize()}: {count}"
    param_line2 = f"Closer {line_label.lower()} {item_plural}: {'Yes' + waist_info if use_closer_waist_pair else 'No'}"
    svg.extend(
        [
            f'<rect x="{page_margin}" y="{param_y - 5}" width="{page_w - 2 * page_margin}" height="26" fill="#f8fafc" stroke="#e2e8f0" stroke-width="0.4" rx="1"/>',
            f'<text x="{page_margin + 3}" y="{param_y + 3}" font-size="4.8" fill="#334155">{param_line1}</text>',
            f'<text x="{page_margin + 3}" y="{param_y + 10}" font-size="4.8" fill="#334155">{param_line2}</text>',
            f'<text x="{page_margin + 3}" y="{param_y + 18}" font-size="4.3" fill="#64748b">{APP_URL}</text>',
        ]
    )

    svg.append("</svg>")
    return "\n".join(svg), scale, orientation


def build_printable_pdf_letter(
    length_mm: float,
    margin_top_mm: float,
    margin_bottom_mm: float,
    radius_mm: float,
    layout: GrommetLayout,
    use_closer_waist_pair: bool,
    count: int,
    waist_edge_gap_mm: float,
    planner_mode: str,
    item_plural: str,
    line_label: str,
    buttonhole_flip_90: bool,
    buttonhole_flip_last_90: bool,
) -> tuple[bytes, int]:
    if (
        not REPORTLAB_AVAILABLE
        or RL_pagesizes is None
        or RL_units is None
        or RL_canvas_module is None
    ):
        raise RuntimeError("PDF export requested but reportlab is not available.")

    page_w, page_h, page_margin, usable_w, page_count = _letter_landscape_layout(
        length_mm
    )
    scale = 1.0
    page_size = RL_pagesizes.landscape(RL_pagesizes.LETTER)
    buffer = io.BytesIO()
    pdf = RL_canvas_module.Canvas(buffer, pagesize=page_size)

    strip_y = 40.0
    strip_h = max(18.0, (2 * radius_mm * scale) + 8.0)
    center_y = strip_y + (strip_h / 2)

    def mm_to_pt(value_mm: float) -> float:
        return value_mm * RL_units.mm

    def fmt_both(value_mm: float) -> str:
        return f"{value_mm:.2f} mm ({value_mm / MM_PER_INCH:.3f} in)"

    def x_local(global_mm: float, segment_start_mm: float) -> float:
        return page_margin + (global_mm - segment_start_mm)

    for page_index in range(page_count):
        segment_start = page_index * usable_w
        segment_end = min(length_mm, segment_start + usable_w)
        segment_width = segment_end - segment_start

        pdf.setFont("Helvetica", 8)
        pdf.drawString(
            mm_to_pt(10),
            mm_to_pt(page_h - 12),
            f"{item_plural[:-1].capitalize()} template Letter landscape - print at 100% / actual size",
        )
        pdf.drawString(
            mm_to_pt(10),
            mm_to_pt(page_h - 17),
            f"Page {page_index + 1}/{page_count} | Segment {fmt_both(segment_start)}..{fmt_both(segment_end)} | Scale 100%",
        )

        pdf.setLineWidth(0.8)
        pdf.rect(
            mm_to_pt(page_margin),
            mm_to_pt(page_h - (strip_y + strip_h)),
            mm_to_pt(segment_width),
            mm_to_pt(strip_h),
        )

        left_boundary_label = (
            f"X={segment_start:.2f} mm / {segment_start / MM_PER_INCH:.3f} in"
        )
        right_boundary_label = (
            f"X={segment_end:.2f} mm / {segment_end / MM_PER_INCH:.3f} in"
        )
        pdf.setFont("Helvetica", 6)
        pdf.drawString(
            mm_to_pt(page_margin),
            mm_to_pt(page_h - (strip_y + strip_h + 4)),
            left_boundary_label,
        )
        pdf.drawRightString(
            mm_to_pt(page_margin + segment_width),
            mm_to_pt(page_h - (strip_y + strip_h + 4)),
            right_boundary_label,
        )

        local_margin_top = margin_top_mm
        if segment_start <= local_margin_top <= segment_end:
            x = x_local(local_margin_top, segment_start)
            pdf.setDash(1.5, 1.5)
            pdf.line(
                mm_to_pt(x),
                mm_to_pt(page_h - (strip_y - 3)),
                mm_to_pt(x),
                mm_to_pt(page_h - (strip_y + strip_h + 3)),
            )
            pdf.setDash()

        local_margin_bottom = length_mm - margin_bottom_mm
        if segment_start <= local_margin_bottom <= segment_end:
            x = x_local(local_margin_bottom, segment_start)
            pdf.setDash(1.5, 1.5)
            pdf.line(
                mm_to_pt(x),
                mm_to_pt(page_h - (strip_y - 3)),
                mm_to_pt(x),
                mm_to_pt(page_h - (strip_y + strip_h + 3)),
            )
            pdf.setDash()

        if segment_start <= layout.waist_position_mm <= segment_end:
            x = x_local(layout.waist_position_mm, segment_start)
            pdf.setDash(2, 2)
            pdf.line(
                mm_to_pt(x),
                mm_to_pt(page_h - (strip_y - 4)),
                mm_to_pt(x),
                mm_to_pt(page_h - (strip_y + strip_h + 4)),
            )
            pdf.setDash()

        for index, center in enumerate(layout.centers_mm):
            if (center + radius_mm) < segment_start or (
                center - radius_mm
            ) > segment_end:
                continue
            x_center = x_local(center, segment_start)
            if planner_mode == MODE_BUTTONHOLES:
                flipped_90 = _buttonhole_is_flipped(
                    index=index,
                    total=len(layout.centers_mm),
                    flip_all_90=buttonhole_flip_90,
                    flip_last_90=(buttonhole_flip_last_90 and (not buttonhole_flip_90)),
                )
                rect_w, rect_h = _buttonhole_dimensions(2 * radius_mm, 1.0, flipped_90)
                pdf.rect(
                    mm_to_pt(x_center - (rect_w / 2)),
                    mm_to_pt(page_h - (center_y + (rect_h / 2))),
                    mm_to_pt(rect_w),
                    mm_to_pt(rect_h),
                    stroke=1,
                    fill=0,
                )
            else:
                pdf.circle(
                    mm_to_pt(x_center),
                    mm_to_pt(page_h - center_y),
                    mm_to_pt(max(0.8, radius_mm)),
                    stroke=1,
                    fill=0,
                )
            pdf.setDash(1.5, 1.5)
            pdf.line(
                mm_to_pt(x_center),
                mm_to_pt(page_h - (strip_y - 1)),
                mm_to_pt(x_center),
                mm_to_pt(page_h - (strip_y + strip_h + 1)),
            )
            pdf.setDash()

        pdf.setLineWidth(0.5)
        pdf.setDash(1.5, 1.5)
        pdf.line(
            mm_to_pt(page_margin),
            mm_to_pt(page_h - center_y),
            mm_to_pt(page_margin + segment_width),
            mm_to_pt(page_h - center_y),
        )
        pdf.setDash()
        pdf.setLineWidth(0.8)

        if page_index < (page_count - 1):
            pdf.setDash(2, 2)
            pdf.line(
                mm_to_pt(page_margin + segment_width),
                mm_to_pt(page_h - (strip_y - 10)),
                mm_to_pt(page_margin + segment_width),
                mm_to_pt(page_h - (strip_y + strip_h + 10)),
            )
            pdf.setDash()
            pdf.drawString(
                mm_to_pt(page_margin + segment_width - 32),
                mm_to_pt(page_h - (strip_y + strip_h + 12)),
                "Join next page here",
            )

        pdf.setFont("Helvetica", 6)
        feature_size_label = (
            "Length" if planner_mode == MODE_BUTTONHOLES else "Diameter"
        )
        pdf.drawString(
            mm_to_pt(10),
            mm_to_pt(page_h - (strip_y + strip_h + 14)),
            f"Total length: {fmt_both(length_mm)}   Top margin: {fmt_both(margin_top_mm)}   Bottom margin: {fmt_both(margin_bottom_mm)}   {feature_size_label}: {fmt_both(radius_mm * 2)}   {item_plural.capitalize()}: {count}",
        )
        waist_n = (
            (layout.waist_pair_indices[1] - layout.waist_pair_indices[0] + 1)
            if (use_closer_waist_pair and layout.waist_pair_indices is not None)
            else 2
        )
        waist_info = (
            f"Closer {line_label.lower()} {item_plural}: {waist_n}   {line_label} at: {fmt_both(layout.waist_position_mm)}   {line_label} edge gap: {fmt_both(waist_edge_gap_mm)}"
            if use_closer_waist_pair
            else f"Closer {line_label.lower()} {item_plural}: No"
        )
        pdf.drawString(
            mm_to_pt(10), mm_to_pt(page_h - (strip_y + strip_h + 19)), waist_info
        )
        pdf.drawString(
            mm_to_pt(10), mm_to_pt(page_h - (strip_y + strip_h + 24)), APP_URL
        )
        centers_on_page = [
            f"{idx + 1}:{v:.2f}mm/{v / MM_PER_INCH:.3f}in"
            for idx, v in enumerate(layout.centers_mm)
            if segment_start <= v <= segment_end
        ]
        if centers_on_page:
            pdf.drawString(
                mm_to_pt(10),
                mm_to_pt(page_h - (strip_y + strip_h + 29)),
                f"Centers on this page (mm/in): {', '.join(centers_on_page[:10])}",
            )

        pdf.showPage()

    pdf.save()
    return buffer.getvalue(), page_count


def calculate_layout(
    length_mm: float,
    margin_top_mm: float,
    margin_bottom_mm: float,
    radius_mm: float,
    count: int,
    use_closer_waist_pair: bool,
    waist_position_mm: float,
    waist_edge_gap_mm: float,
    waist_count: int = 2,
    item_plural: str = "grommets",
    line_title: str = "waist",
    feature_half_sizes_mm: list[float] | None = None,
) -> GrommetLayout:
    warnings: list[str] = []
    start_center = margin_top_mm + radius_mm
    end_center = length_mm - margin_bottom_mm - radius_mm

    if end_center - start_center < 0:
        warnings.append(
            f"Margins + {item_plural[:-1]} size exceed strip length. Reduce margins/size or increase strip length."
        )
        return GrommetLayout(
            centers_mm=[],
            center_spacings_mm=[],
            edge_gaps_mm=[],
            uniform_center_spacing_mm=None,
            start_center_mm=start_center,
            end_center_mm=end_center,
            waist_position_mm=waist_position_mm,
            waist_pair_indices=None,
            warnings=warnings,
        )

    if count == 1:
        center = length_mm / 2
        if center - radius_mm < margin_top_mm or center + radius_mm > (
            length_mm - margin_bottom_mm
        ):
            warnings.append(
                f"Single {item_plural[:-1]} does not fit inside strip with the selected margins/size."
            )
        center_spacings, edge_gaps, uniform_spacing = _build_spacing_lists(
            [center], radius_mm, feature_half_sizes_mm
        )
        return GrommetLayout(
            centers_mm=[center],
            center_spacings_mm=center_spacings,
            edge_gaps_mm=edge_gaps,
            uniform_center_spacing_mm=uniform_spacing,
            start_center_mm=center,
            end_center_mm=center,
            waist_position_mm=waist_position_mm,
            waist_pair_indices=None,
            warnings=warnings,
        )

    if not use_closer_waist_pair:
        span_for_centers = end_center - start_center
        center_spacing = span_for_centers / (count - 1)
        centers = [start_center + i * center_spacing for i in range(count)]
        center_spacings, edge_gaps, uniform_spacing = _build_spacing_lists(
            centers, radius_mm, feature_half_sizes_mm
        )
        if edge_gaps and min(edge_gaps) < 0:
            warnings.append(
                f"{item_plural.capitalize()} overlap with current settings (negative edge-to-edge gap)."
            )

        return GrommetLayout(
            centers_mm=centers,
            center_spacings_mm=center_spacings,
            edge_gaps_mm=edge_gaps,
            uniform_center_spacing_mm=uniform_spacing,
            start_center_mm=centers[0],
            end_center_mm=centers[-1],
            waist_position_mm=waist_position_mm,
            waist_pair_indices=None,
            warnings=warnings,
        )

    if count < waist_count:
        warnings.append(
            f"Closer {line_title} arrangement requires at least {waist_count} {item_plural}."
        )
        return GrommetLayout(
            centers_mm=[],
            center_spacings_mm=[],
            edge_gaps_mm=[],
            uniform_center_spacing_mm=None,
            start_center_mm=start_center,
            end_center_mm=end_center,
            waist_position_mm=waist_position_mm,
            waist_pair_indices=None,
            warnings=warnings,
        )

    waist_center_spacing = (2 * radius_mm) + waist_edge_gap_mm
    total_waist_span = (waist_count - 1) * waist_center_spacing
    left_waist_center = waist_position_mm - (total_waist_span / 2)
    right_waist_center = waist_position_mm + (total_waist_span / 2)
    waist_centers_list = [
        left_waist_center + i * waist_center_spacing for i in range(waist_count)
    ]

    if left_waist_center < start_center or right_waist_center > end_center:
        warnings.append(
            f"{line_title.capitalize()} {item_plural} do not fit between margins. Reduce {line_title} gap/size, move {line_title}, or increase strip length."
        )
    if waist_count > 1 and left_waist_center >= right_waist_center:
        warnings.append(f"Invalid {line_title} arrangement geometry.")

    remaining_count = count - waist_count
    left_span = max(0.0, left_waist_center - start_center)
    right_span = max(0.0, end_center - right_waist_center)
    total_span = left_span + right_span

    if remaining_count > 0 and total_span > 0:
        proportional_left = remaining_count * (left_span / total_span)
        left_count = int(round(proportional_left))
        left_count = max(0, min(left_count, remaining_count))
        right_count = remaining_count - left_count
    else:
        left_count = 0
        right_count = remaining_count

    if left_span == 0:
        left_count = 0
        right_count = remaining_count
    if right_span == 0:
        right_count = 0
        left_count = remaining_count

    centers: list[float] = []

    if left_count > 0:
        step_left = (left_waist_center - start_center) / left_count
        if step_left <= 0:
            warnings.append(
                f"No space for left-side {item_plural} before the {line_title} cluster."
            )
        centers.extend(start_center + i * step_left for i in range(left_count))

    centers.extend(waist_centers_list)

    if right_count > 0:
        step_right = (end_center - right_waist_center) / right_count
        if step_right <= 0:
            warnings.append(
                f"No space for right-side {item_plural} after the {line_title} cluster."
            )
        centers.extend(
            right_waist_center + j * step_right for j in range(1, right_count + 1)
        )

    if any(centers[i + 1] <= centers[i] for i in range(len(centers) - 1)):
        warnings.append(
            "Computed centers are not strictly increasing. Check waist position and gap values."
        )

    center_spacings, edge_gaps, uniform_spacing = _build_spacing_lists(
        centers, radius_mm, feature_half_sizes_mm
    )
    if edge_gaps and min(edge_gaps) < 0:
        warnings.append(
            f"{item_plural.capitalize()} overlap with current settings (negative edge-to-edge gap)."
        )

    return GrommetLayout(
        centers_mm=centers,
        center_spacings_mm=center_spacings,
        edge_gaps_mm=edge_gaps,
        uniform_center_spacing_mm=uniform_spacing,
        start_center_mm=centers[0] if centers else start_center,
        end_center_mm=centers[-1] if centers else end_center,
        waist_position_mm=waist_position_mm,
        waist_pair_indices=(left_count, left_count + waist_count - 1),
        warnings=warnings,
    )


def _auto_bottom_margin_for_bust_alignment(
    length_mm: float,
    margin_top_mm: float,
    radius_mm: float,
    bust_position_mm: float,
    count: int,
) -> tuple[float | None, int | None]:
    if count < 2:
        return None, None

    start_center = margin_top_mm + radius_mm
    max_center = length_mm - radius_mm
    available_span = max_center - start_center
    bust_offset = bust_position_mm - start_center

    if available_span <= 0 or bust_offset <= 0:
        return None, None

    tolerance = 1e-9
    min_step_exclusive = available_span / count
    max_step_inclusive = available_span / (count - 1)

    best_step: float | None = None
    best_bust_index: int | None = None

    for bust_index in range(1, count):
        step = bust_offset / bust_index
        if step <= 0:
            continue
        if (step > (min_step_exclusive + tolerance)) and (
            step <= (max_step_inclusive + tolerance)
        ):
            if best_step is None or step > best_step:
                best_step = step
                best_bust_index = bust_index

    if best_step is None or best_bust_index is None:
        return None, None

    last_center = start_center + ((count - 1) * best_step)
    bottom_margin_mm = length_mm - (last_center + radius_mm)

    if bottom_margin_mm < -tolerance:
        return None, None

    return max(0.0, bottom_margin_mm), best_bust_index


def build_svg(
    length_mm: float,
    margin_top_mm: float,
    margin_bottom_mm: float,
    radius_mm: float,
    layout: GrommetLayout,
    use_closer_waist_pair: bool,
    display_unit: str,
    display_factor: float,
    planner_mode: str,
    line_label: str,
    buttonhole_flip_90: bool,
    buttonhole_flip_last_90: bool,
) -> str:
    width_px = 1000
    strip_h_px = 120
    pad_x = 40
    pad_y = 30
    view_w = width_px + pad_x * 2
    view_h = 380

    scale_x = width_px / max(length_mm, 1)
    center_y = pad_y + strip_h_px / 2

    def x_mm(mm: float) -> float:
        return pad_x + mm * scale_x

    def disp(mm_value: float) -> float:
        return mm_value * display_factor

    rect_x = x_mm(0)
    rect_y = pad_y
    rect_w = x_mm(length_mm) - x_mm(0)

    svg = [
        f'<svg viewBox="0 0 {view_w} {view_h}" width="100%" xmlns="http://www.w3.org/2000/svg">',
        f'<rect x="{rect_x}" y="{rect_y}" width="{rect_w}" height="{strip_h_px}" fill="#f4f4f5" stroke="#3f3f46" stroke-width="1.5"/>',
        f'<line x1="{x_mm(0)}" y1="{rect_y + strip_h_px + 40}" x2="{x_mm(length_mm)}" y2="{rect_y + strip_h_px + 40}" stroke="#3f3f46" stroke-width="1"/>',
        f'<line x1="{x_mm(0)}" y1="{rect_y + strip_h_px + 34}" x2="{x_mm(0)}" y2="{rect_y + strip_h_px + 46}" stroke="#3f3f46" stroke-width="1"/>',
        f'<line x1="{x_mm(length_mm)}" y1="{rect_y + strip_h_px + 34}" x2="{x_mm(length_mm)}" y2="{rect_y + strip_h_px + 46}" stroke="#3f3f46" stroke-width="1"/>',
        f'<text x="{(x_mm(0) + x_mm(length_mm)) / 2}" y="{rect_y + strip_h_px + 62}" text-anchor="middle" font-size="14" fill="#18181b">Total length: {disp(length_mm):.2f} {display_unit}</text>',
    ]

    margin_y = rect_y - 10
    svg.extend(
        [
            f'<line x1="{x_mm(0)}" y1="{margin_y}" x2="{x_mm(margin_top_mm)}" y2="{margin_y}" stroke="#0ea5e9" stroke-width="1.5"/>',
            f'<line x1="{x_mm(length_mm - margin_bottom_mm)}" y1="{margin_y}" x2="{x_mm(length_mm)}" y2="{margin_y}" stroke="#0ea5e9" stroke-width="1.5"/>',
            f'<text x="{(x_mm(0) + x_mm(margin_top_mm)) / 2}" y="{margin_y - 6}" text-anchor="middle" font-size="12" fill="#0369a1">Top margin: {disp(margin_top_mm):.2f} {display_unit}</text>',
            f'<text x="{(x_mm(length_mm - margin_bottom_mm) + x_mm(length_mm)) / 2}" y="{margin_y - 6}" text-anchor="middle" font-size="12" fill="#0369a1">Bottom margin: {disp(margin_bottom_mm):.2f} {display_unit}</text>',
        ]
    )

    waist_x_mm = layout.waist_position_mm
    if 0 <= waist_x_mm <= length_mm:
        svg.extend(
            [
                f'<line x1="{x_mm(waist_x_mm)}" y1="{rect_y - 2}" x2="{x_mm(waist_x_mm)}" y2="{rect_y + strip_h_px + 2}" stroke="#dc2626" stroke-dasharray="4 4" stroke-width="1.5"/>',
                f'<text x="{x_mm(waist_x_mm)}" y="{rect_y + strip_h_px + 16}" text-anchor="middle" font-size="12" fill="#b91c1c">{line_label}: {disp(waist_x_mm):.2f} {display_unit}</text>',
            ]
        )

    waist_left = waist_right = None
    if layout.waist_pair_indices is not None and layout.waist_pair_indices[1] < len(
        layout.centers_mm
    ):
        waist_left = layout.centers_mm[layout.waist_pair_indices[0]]
        waist_right = layout.centers_mm[layout.waist_pair_indices[1]]

    for index, center in enumerate(layout.centers_mm):
        is_waist_pair = (
            layout.waist_pair_indices is not None
            and layout.waist_pair_indices[0] <= index <= layout.waist_pair_indices[1]
            and use_closer_waist_pair
        )
        fill = "#fdba74" if is_waist_pair else "#bfdbfe"
        stroke = "#c2410c" if is_waist_pair else "#1d4ed8"
        if planner_mode == MODE_BUTTONHOLES:
            flipped_90 = _buttonhole_is_flipped(
                index=index,
                total=len(layout.centers_mm),
                flip_all_90=buttonhole_flip_90,
                flip_last_90=(buttonhole_flip_last_90 and (not buttonhole_flip_90)),
            )
            rect_w, rect_h = _buttonhole_dimensions(2 * radius_mm, scale_x, flipped_90)
            shape = f'<rect x="{x_mm(center) - (rect_w / 2)}" y="{center_y - (rect_h / 2)}" width="{rect_w}" height="{rect_h}" rx="2" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
        else:
            shape = f'<circle cx="{x_mm(center)}" cy="{center_y}" r="{radius_mm * scale_x}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
        svg.extend(
            [
                shape,
                f'<line x1="{x_mm(center)}" y1="{rect_y}" x2="{x_mm(center)}" y2="{rect_y + strip_h_px}" stroke="{stroke}" stroke-dasharray="3 3" stroke-width="1"/>',
            ]
        )

    svg.append(
        f'<line x1="{x_mm(0)}" y1="{center_y}" x2="{x_mm(length_mm)}" y2="{center_y}" stroke="#1d4ed8" stroke-width="1" stroke-dasharray="3 3"/>'
    )

    standard_pair_index = _find_standard_pair_index(layout, use_closer_waist_pair)

    # Determine the last lower pair (last two grommets after the waist cluster)
    lower_pair_index: int | None = None
    if use_closer_waist_pair and layout.waist_pair_indices is not None:
        last = len(layout.centers_mm) - 1
        if last > layout.waist_pair_indices[1]:
            lower_pair_index = last - 1

    upper_label = "Upper center-to-center" if (use_closer_waist_pair and layout.waist_pair_indices is not None) else "Standard center-to-center"
    upper_gap_label = "Upper edge gap" if (use_closer_waist_pair and layout.waist_pair_indices is not None) else "Standard edge gap"

    y_dim_c2c = rect_y + strip_h_px + 28
    y_dim_gap = rect_y + strip_h_px + 62

    if standard_pair_index is not None:
        c1 = layout.centers_mm[standard_pair_index]
        c2 = layout.centers_mm[standard_pair_index + 1]
        center_to_center = c2 - c1
        standard_edge_gap = center_to_center - (2 * radius_mm)

        svg.extend(
            [
                f'<line x1="{x_mm(c1)}" y1="{y_dim_c2c}" x2="{x_mm(c2)}" y2="{y_dim_c2c}" stroke="#16a34a" stroke-width="1.5"/>',
                f'<line x1="{x_mm(c1)}" y1="{y_dim_c2c - 5}" x2="{x_mm(c1)}" y2="{y_dim_c2c + 5}" stroke="#16a34a" stroke-width="1"/>',
                f'<line x1="{x_mm(c2)}" y1="{y_dim_c2c - 5}" x2="{x_mm(c2)}" y2="{y_dim_c2c + 5}" stroke="#16a34a" stroke-width="1"/>',
                f'<text x="{(x_mm(c1) + x_mm(c2)) / 2}" y="{y_dim_c2c - 6}" text-anchor="middle" font-size="12" fill="#166534">{upper_label}: {disp(center_to_center):.2f} {display_unit}</text>',
                f'<line x1="{x_mm(c1 + radius_mm)}" y1="{y_dim_gap}" x2="{x_mm(c2 - radius_mm)}" y2="{y_dim_gap}" stroke="#0f766e" stroke-width="1.5"/>',
                f'<line x1="{x_mm(c1 + radius_mm)}" y1="{y_dim_gap - 5}" x2="{x_mm(c1 + radius_mm)}" y2="{y_dim_gap + 5}" stroke="#0f766e" stroke-width="1"/>',
                f'<line x1="{x_mm(c2 - radius_mm)}" y1="{y_dim_gap - 5}" x2="{x_mm(c2 - radius_mm)}" y2="{y_dim_gap + 5}" stroke="#0f766e" stroke-width="1"/>',
                f'<text x="{(x_mm(c1) + x_mm(c2)) / 2}" y="{y_dim_gap - 6}" text-anchor="middle" font-size="12" fill="#0f766e">{upper_gap_label}: {disp(standard_edge_gap):.2f} {display_unit}</text>',
            ]
        )

    if lower_pair_index is not None:
        lc1 = layout.centers_mm[lower_pair_index]
        lc2 = layout.centers_mm[lower_pair_index + 1]
        lower_c2c = lc2 - lc1
        lower_edge_gap = lower_c2c - (2 * radius_mm)
        svg.extend(
            [
                f'<line x1="{x_mm(lc1)}" y1="{y_dim_c2c}" x2="{x_mm(lc2)}" y2="{y_dim_c2c}" stroke="#16a34a" stroke-width="1.5"/>',
                f'<line x1="{x_mm(lc1)}" y1="{y_dim_c2c - 5}" x2="{x_mm(lc1)}" y2="{y_dim_c2c + 5}" stroke="#16a34a" stroke-width="1"/>',
                f'<line x1="{x_mm(lc2)}" y1="{y_dim_c2c - 5}" x2="{x_mm(lc2)}" y2="{y_dim_c2c + 5}" stroke="#16a34a" stroke-width="1"/>',
                f'<text x="{(x_mm(lc1) + x_mm(lc2)) / 2}" y="{y_dim_c2c - 6}" text-anchor="middle" font-size="12" fill="#166534">Lower center-to-center: {disp(lower_c2c):.2f} {display_unit}</text>',
                f'<line x1="{x_mm(lc1 + radius_mm)}" y1="{y_dim_gap}" x2="{x_mm(lc2 - radius_mm)}" y2="{y_dim_gap}" stroke="#0f766e" stroke-width="1.5"/>',
                f'<line x1="{x_mm(lc1 + radius_mm)}" y1="{y_dim_gap - 5}" x2="{x_mm(lc1 + radius_mm)}" y2="{y_dim_gap + 5}" stroke="#0f766e" stroke-width="1"/>',
                f'<line x1="{x_mm(lc2 - radius_mm)}" y1="{y_dim_gap - 5}" x2="{x_mm(lc2 - radius_mm)}" y2="{y_dim_gap + 5}" stroke="#0f766e" stroke-width="1"/>',
                f'<text x="{(x_mm(lc1) + x_mm(lc2)) / 2}" y="{y_dim_gap - 6}" text-anchor="middle" font-size="12" fill="#0f766e">Lower edge gap: {disp(lower_edge_gap):.2f} {display_unit}</text>',
            ]
        )

    if use_closer_waist_pair and layout.waist_pair_indices is not None:
        waist_start_index = layout.waist_pair_indices[0]
        waist_end_index = layout.waist_pair_indices[1]
        if waist_end_index > waist_start_index and waist_end_index < len(
            layout.centers_mm
        ):
            waist_left = layout.centers_mm[waist_start_index]
            waist_right = layout.centers_mm[waist_start_index + 1]
        else:
            waist_left = waist_right = None

    if use_closer_waist_pair and waist_left is not None and waist_right is not None:
        y_c2c_waist = rect_y + 14
        waist_center_to_center = waist_right - waist_left
        svg.extend(
            [
                f'<line x1="{x_mm(waist_left)}" y1="{y_c2c_waist}" x2="{x_mm(waist_right)}" y2="{y_c2c_waist}" stroke="#b45309" stroke-width="1.6"/>',
                f'<line x1="{x_mm(waist_left)}" y1="{y_c2c_waist - 5}" x2="{x_mm(waist_left)}" y2="{y_c2c_waist + 5}" stroke="#b45309" stroke-width="1"/>',
                f'<line x1="{x_mm(waist_right)}" y1="{y_c2c_waist - 5}" x2="{x_mm(waist_right)}" y2="{y_c2c_waist + 5}" stroke="#b45309" stroke-width="1"/>',
                f'<text x="{(x_mm(waist_left) + x_mm(waist_right)) / 2}" y="{y_c2c_waist - 6}" text-anchor="middle" font-size="12" fill="#92400e">{line_label} center-to-center: {disp(waist_center_to_center):.2f} {display_unit}</text>',
            ]
        )

        y_gap = rect_y + strip_h_px + 96
        svg.extend(
            [
                f'<line x1="{x_mm(waist_left + radius_mm)}" y1="{y_gap}" x2="{x_mm(waist_right - radius_mm)}" y2="{y_gap}" stroke="#ea580c" stroke-width="1.6"/>',
                f'<line x1="{x_mm(waist_left + radius_mm)}" y1="{y_gap - 5}" x2="{x_mm(waist_left + radius_mm)}" y2="{y_gap + 5}" stroke="#ea580c" stroke-width="1"/>',
                f'<line x1="{x_mm(waist_right - radius_mm)}" y1="{y_gap - 5}" x2="{x_mm(waist_right - radius_mm)}" y2="{y_gap + 5}" stroke="#ea580c" stroke-width="1"/>',
                f'<text x="{(x_mm(waist_left) + x_mm(waist_right)) / 2}" y="{y_gap - 6}" text-anchor="middle" font-size="12" fill="#9a3412">{line_label} edge gap: {disp(waist_right - waist_left - (2 * radius_mm)):.2f} {display_unit}</text>',
            ]
        )

    svg.append("</svg>")
    return "\n".join(svg)


def main() -> None:
    st.set_page_config(
        page_title="Grommets and Buttonholes Planner",
        layout="wide",
        menu_items={
            "Get help": "https://github.com/adumont/grommet-planner?tab=readme-ov-file#grommets-and-buttonholes-planner",
            "About": "Grommets and Buttonholes Planner - plan your grommet/buttonhole layout and print templates for accurate placement when sewing. Contact me at [@sewing.alex](https://www.instagram.com/sewing.alex)",
        },
    )

    if "length_mm" not in st.session_state:
        st.session_state.length_mm = 330.0
    if "margin_top_mm" not in st.session_state:
        st.session_state.margin_top_mm = 20.0
    if "margin_bottom_mm" not in st.session_state:
        st.session_state.margin_bottom_mm = 20.0
    if "diameter_mm" not in st.session_state:
        st.session_state.diameter_mm = 10.0
    if "waist_position_mm" not in st.session_state:
        st.session_state.waist_position_mm = 170.0
    if "waist_edge_gap_mm" not in st.session_state:
        st.session_state.waist_edge_gap_mm = 16.0
    if "grommet_count" not in st.session_state:
        st.session_state.grommet_count = 10
    if "item_count" not in st.session_state:
        st.session_state.item_count = st.session_state.grommet_count
    if "use_closer_waist_pair" not in st.session_state:
        st.session_state.use_closer_waist_pair = True
    if "waist_count" not in st.session_state:
        st.session_state.waist_count = 2
    if "planner_mode" not in st.session_state:
        st.session_state.planner_mode = MODE_GROMMETS
    if "_prev_planner_mode" not in st.session_state:
        st.session_state._prev_planner_mode = st.session_state.planner_mode
    if "_flip_all_90" not in st.session_state:
        st.session_state._flip_all_90 = False
    if "_flip_last_90" not in st.session_state:
        st.session_state._flip_last_90 = True
    if "bust_count" not in st.session_state:
        st.session_state.bust_count = 1
    if "unit_mode" not in st.session_state:
        st.session_state.unit_mode = False
    if "_prev_unit_mode" not in st.session_state:
        st.session_state._prev_unit_mode = st.session_state.unit_mode
    if "_pending_auto_bottom_margin_calc" not in st.session_state:
        st.session_state._pending_auto_bottom_margin_calc = False
    if "_auto_bottom_margin_feedback" not in st.session_state:
        st.session_state._auto_bottom_margin_feedback = None

    terms = _planner_terms(st.session_state.planner_mode)

    if st.session_state._pending_auto_bottom_margin_calc:
        st.session_state._pending_auto_bottom_margin_calc = False
        if (
            st.session_state.planner_mode == MODE_BUTTONHOLES
            and st.session_state.use_closer_waist_pair
        ):
            bottom_margin_mm, bust_index = _auto_bottom_margin_for_bust_alignment(
                length_mm=float(st.session_state.length_mm),
                margin_top_mm=float(st.session_state.margin_top_mm),
                radius_mm=float(st.session_state.diameter_mm) / 2,
                bust_position_mm=float(st.session_state.waist_position_mm),
                count=int(st.session_state.item_count),
            )
            if bottom_margin_mm is None:
                st.session_state._auto_bottom_margin_feedback = (
                    "warning",
                    "No exact spacing solution found. Try one less buttonhole or move the bust position and try again.",
                )
            else:
                bust_index_value = bust_index if bust_index is not None else 0
                st.session_state.bust_count = 1
                st.session_state.margin_bottom_mm = bottom_margin_mm
                output_factor = 1 / MM_PER_INCH if st.session_state.unit_mode else 1.0
                st.session_state.margin_bottom_display = bottom_margin_mm * output_factor
                st.session_state._auto_bottom_margin_feedback = (
                    "success",
                    f"Bottom margin set to {bottom_margin_mm * output_factor:.2f} {'in' if st.session_state.unit_mode else 'mm'}. Bust buttonholes reset to 1; button #{bust_index_value + 1} is exactly at the bust.",
                )
        else:
            st.session_state._auto_bottom_margin_feedback = None

    st.title(terms["app_title"])
    st.write(terms["app_subtitle"])

    def _sync_display_from_mm() -> None:
        factor = 1 / MM_PER_INCH if st.session_state.unit_mode else 1.0
        st.session_state.length_display = st.session_state.length_mm * factor
        st.session_state.margin_top_display = st.session_state.margin_top_mm * factor
        st.session_state.margin_bottom_display = (
            st.session_state.margin_bottom_mm * factor
        )
        st.session_state.diameter_display = st.session_state.diameter_mm * factor
        st.session_state.waist_position_display = (
            st.session_state.waist_position_mm * factor
        )
        st.session_state.waist_edge_gap_display = (
            st.session_state.waist_edge_gap_mm * factor
        )

    if "length_display" not in st.session_state:
        _sync_display_from_mm()

    def _display_to_mm_factor() -> float:
        return MM_PER_INCH if st.session_state.unit_mode else 1.0

    def _update_length_mm() -> None:
        st.session_state.length_mm = (
            st.session_state.length_display * _display_to_mm_factor()
        )
        st.session_state.waist_position_mm = min(
            max(0.0, st.session_state.waist_position_mm), st.session_state.length_mm
        )
        st.session_state.waist_position_display = (
            st.session_state.waist_position_mm / _display_to_mm_factor()
        )

    def _update_margin_top_mm() -> None:
        st.session_state.margin_top_mm = (
            st.session_state.margin_top_display * _display_to_mm_factor()
        )

    def _update_margin_bottom_mm() -> None:
        st.session_state.margin_bottom_mm = (
            st.session_state.margin_bottom_display * _display_to_mm_factor()
        )

    def _update_diameter_mm() -> None:
        st.session_state.diameter_mm = (
            st.session_state.diameter_display * _display_to_mm_factor()
        )

    def _update_waist_position_mm() -> None:
        st.session_state.waist_position_mm = (
            st.session_state.waist_position_display * _display_to_mm_factor()
        )

    def _update_waist_edge_gap_mm() -> None:
        st.session_state.waist_edge_gap_mm = (
            st.session_state.waist_edge_gap_display * _display_to_mm_factor()
        )

    left, right = st.columns([1, 2], gap="large")
    buttonhole_flip_90_ui = st.session_state._flip_all_90
    buttonhole_flip_last_90_ui = st.session_state._flip_last_90

    with left:
        planner_mode = st.radio(
            "Planner mode",
            options=[MODE_GROMMETS, MODE_BUTTONHOLES],
            key="planner_mode",
            horizontal=True,
        )
        terms = _planner_terms(planner_mode)

        if planner_mode != st.session_state._prev_planner_mode:
            if planner_mode == MODE_BUTTONHOLES:
                st.session_state.waist_position_mm = 130.0
            else:
                st.session_state.waist_position_mm = 170.0
            _sync_display_from_mm()
            st.session_state._prev_planner_mode = planner_mode

        unit_mode = st.toggle(
            "Use imperial units (inches)",
            key="unit_mode",
            help="Switch between millimetres and inches for all inputs and displayed values.",
        )

        if unit_mode != st.session_state._prev_unit_mode:
            _sync_display_from_mm()
            st.session_state._prev_unit_mode = unit_mode

        unit_label = "in" if unit_mode else "mm"
        input_to_mm = MM_PER_INCH if unit_mode else 1.0
        mm_to_output = 1 / MM_PER_INCH if unit_mode else 1.0

        length_input = st.number_input(
            f"Strip length ({unit_label})",
            min_value=0.1 if unit_mode else 1.0,
            step=0.01 if unit_mode else 1.0,
            format="%.2f" if unit_mode else "%.1f",
            key="length_display",
            on_change=_update_length_mm,
            help=f"Total length of the strip where {terms['item_plural']} will be placed.",
        )
        margin_top_input = st.number_input(
            f"Top end margin ({unit_label})",
            min_value=0.0,
            step=0.01 if unit_mode else 0.5,
            format="%.2f" if unit_mode else "%.1f",
            key="margin_top_display",
            on_change=_update_margin_top_mm,
            help=f"Distance from the top strip end to the nearest {terms['item_singular']} edge.",
        )
        margin_bottom_input = st.number_input(
            f"Bottom end margin ({unit_label})",
            min_value=0.0,
            step=0.01 if unit_mode else 0.5,
            format="%.2f" if unit_mode else "%.1f",
            key="margin_bottom_display",
            on_change=_update_margin_bottom_mm,
            help=f"Distance from the bottom strip end to the nearest {terms['item_singular']} edge.",
        )
        diameter_input = st.number_input(
            f"{terms['size_label']} ({unit_label})",
            min_value=0.01 if unit_mode else 1.0,
            step=0.01 if unit_mode else 1.0,
            format="%.2f" if unit_mode else "%.1f",
            key="diameter_display",
            on_change=_update_diameter_mm,
            help=(
                "Outside diameter of the grommet ring (not the inner hole)."
                if planner_mode == MODE_GROMMETS
                else "Buttonhole length measured along the strip."
            ),
        )

        length_mm = length_input * input_to_mm
        margin_top_mm = margin_top_input * input_to_mm
        margin_bottom_mm = margin_bottom_input * input_to_mm
        diameter_mm = diameter_input * input_to_mm
        radius_mm = diameter_mm / 2
        count = st.number_input(
            f"Number of {terms['item_plural']}",
            min_value=1,
            step=1,
            key="item_count",
            help=f"Total number of {terms['item_plural']} along the strip.",
        )
        waist_position_mm = (
            st.number_input(
                f"{terms['line']} position from top ({unit_label})",
                min_value=0.0,
                max_value=float(length_input),
                step=0.01 if unit_mode else 0.5,
                format="%.2f" if unit_mode else "%.1f",
                key="waist_position_display",
                on_change=_update_waist_position_mm,
                help=f"Target {terms['line_lower']} location measured from the top of the strip.",
            )
            * input_to_mm
        )

        if planner_mode == MODE_BUTTONHOLES:
            buttonhole_flip_90_ui = st.checkbox(
                "Flip buttonholes 90°",
                key="_flip_all_90",
                help="Rotate buttonhole rectangles by 90° in the diagram and exports.",
            )
            buttonhole_flip_last_90_ui = st.checkbox(
                "Flip last button 90°",
                key="_flip_last_90",
                disabled=buttonhole_flip_90_ui,
                help="Rotate only the last buttonhole by 90° in the diagram and exports.",
            )

        use_closer_waist_pair = st.checkbox(
            f"Closer {terms['line_lower']} {terms['item_plural']}",
            key="use_closer_waist_pair",
            help=f"Places the {terms['line_lower']} {terms['item_plural']} closer together than the standard spacing.",
        )

        if planner_mode == MODE_BUTTONHOLES:
            waist_count = st.number_input(
                "Number of bust buttonholes",
                min_value=1,
                step=2,
                key="bust_count",
                disabled=not use_closer_waist_pair,
                help="Odd number of buttonholes in the closer bust cluster, centered on the bust line.",
            )
            if int(waist_count) % 2 == 0:
                waist_count = int(waist_count) + 1
                st.session_state.bust_count = int(waist_count)
                st.info(
                    f"Bust buttonholes count must be odd. Using {int(waist_count)}."
                )
        else:
            waist_count = st.number_input(
                "Number of waist grommets",
                min_value=2,
                value=2,
                step=1,
                key="waist_count",
                disabled=not use_closer_waist_pair,
                help="How many grommets to place at the waist, evenly spaced and centered on the waist position.",
            )
        cluster_edge_gap_enabled = (
            use_closer_waist_pair
            and (planner_mode != MODE_BUTTONHOLES or int(waist_count) > 1)
        )
        waist_edge_gap_mm = (
            st.number_input(
                f"{terms['line']} cluster edge gap ({unit_label})",
                min_value=0.0,
                step=0.01 if unit_mode else 0.5,
                format="%.2f" if unit_mode else "%.1f",
                key="waist_edge_gap_display",
                on_change=_update_waist_edge_gap_mm,
                disabled=not cluster_edge_gap_enabled,
                help=f"Edge-to-edge distance between adjacent {terms['line_lower']} {terms['item_plural']}, centered at the {terms['line_lower']} position.",
            )
            * input_to_mm
        )

        st.session_state.length_mm = length_mm
        st.session_state.margin_top_mm = margin_top_mm
        st.session_state.margin_bottom_mm = margin_bottom_mm
        st.session_state.diameter_mm = diameter_mm
        st.session_state.waist_position_mm = waist_position_mm
        st.session_state.waist_edge_gap_mm = waist_edge_gap_mm
        st.session_state.grommet_count = int(count)

    effective_buttonhole_flip_90 = (
        planner_mode == MODE_BUTTONHOLES and buttonhole_flip_90_ui
    )
    effective_buttonhole_flip_last_90 = (
        planner_mode == MODE_BUTTONHOLES
        and (not buttonhole_flip_90_ui)
        and buttonhole_flip_last_90_ui
    )

    feature_half_sizes_mm = [radius_mm] * int(count)
    if planner_mode == MODE_BUTTONHOLES:
        for idx in range(int(count)):
            is_flipped = _buttonhole_is_flipped(
                index=idx,
                total=int(count),
                flip_all_90=effective_buttonhole_flip_90,
                flip_last_90=effective_buttonhole_flip_last_90,
            )
            feature_half_sizes_mm[idx] = _buttonhole_half_extent_mm(
                2 * radius_mm, is_flipped
            )

    layout = calculate_layout(
        length_mm=length_mm,
        margin_top_mm=margin_top_mm,
        margin_bottom_mm=margin_bottom_mm,
        radius_mm=radius_mm,
        count=count,
        use_closer_waist_pair=use_closer_waist_pair,
        waist_position_mm=waist_position_mm,
        waist_edge_gap_mm=waist_edge_gap_mm,
        waist_count=int(waist_count),
        item_plural=terms["item_plural"],
        line_title=terms["line_lower"],
        feature_half_sizes_mm=feature_half_sizes_mm,
    )

    with right:
        st.subheader("Layout diagram")
        components.html(
            build_svg(
                length_mm=length_mm,
                margin_top_mm=margin_top_mm,
                margin_bottom_mm=margin_bottom_mm,
                radius_mm=radius_mm,
                layout=layout,
                use_closer_waist_pair=use_closer_waist_pair,
                display_unit=unit_label,
                display_factor=mm_to_output,
                planner_mode=planner_mode,
                line_label=terms["line"],
                buttonhole_flip_90=effective_buttonhole_flip_90,
                buttonhole_flip_last_90=effective_buttonhole_flip_last_90,
            ),
            height=400,
        )

        if planner_mode == MODE_BUTTONHOLES and use_closer_waist_pair:
            st.caption(
                "Set bust cluster to 1 and compute bottom margin so spacing is even, top buttonhole stays at top margin, and one buttonhole lands exactly on bust."
            )
            if st.button(
                "Auto-calculate bottom margin from bust alignment",
                use_container_width=True,
            ):
                st.session_state._pending_auto_bottom_margin_calc = True
                st.rerun()

            feedback = st.session_state.get("_auto_bottom_margin_feedback")
            if isinstance(feedback, tuple) and len(feedback) == 2:
                level, message = feedback
                if level == "success":
                    st.success(message)
                elif level == "warning":
                    st.warning(message)

    metric_cols = st.columns(4)
    metric_cols[0].metric(terms["item_plural"].capitalize(), f"{count}")
    metric_cols[1].metric(
        "First center", f"{layout.start_center_mm * mm_to_output:.2f} {unit_label}"
    )
    metric_cols[2].metric(
        "Last center", f"{layout.end_center_mm * mm_to_output:.2f} {unit_label}"
    )
    metric_cols[3].metric(
        f"{terms['line']} position",
        f"{waist_position_mm * mm_to_output:.2f} {unit_label}",
    )

    # derive left / waist / right spacing + gap values
    def _fmt(v: float | None) -> str:
        return f"{(v * mm_to_output):.2f} {unit_label}" if v is not None else "—"

    if (
        layout.center_spacings_mm
        and use_closer_waist_pair
        and layout.waist_pair_indices is not None
    ):
        wi_l, wi_r = layout.waist_pair_indices
        left_spacings = layout.center_spacings_mm[:wi_l]
        waist_spacing = (
            layout.center_spacings_mm[wi_l]
            if wi_l < len(layout.center_spacings_mm)
            else None
        )
        right_spacings = layout.center_spacings_mm[wi_r:]
        left_gaps = layout.edge_gaps_mm[:wi_l]
        waist_gap = (
            layout.edge_gaps_mm[wi_l] if wi_l < len(layout.edge_gaps_mm) else None
        )
        right_gaps = layout.edge_gaps_mm[wi_r:]
        sp_left = _fmt(left_spacings[0] if left_spacings else None)
        sp_waist = _fmt(waist_spacing)
        sp_right = _fmt(right_spacings[-1] if right_spacings else None)
        eg_left = _fmt(left_gaps[0] if left_gaps else None)
        eg_waist = _fmt(waist_gap)
        eg_right = _fmt(right_gaps[-1] if right_gaps else None)
    elif layout.center_spacings_mm:
        uniform = (
            _fmt(layout.uniform_center_spacing_mm)
            if layout.uniform_center_spacing_mm is not None
            else f"{min(layout.center_spacings_mm) * mm_to_output:.2f}..{max(layout.center_spacings_mm) * mm_to_output:.2f} {unit_label}"
        )
        sp_left = sp_waist = sp_right = uniform
        eg_val = (
            _fmt(layout.edge_gaps_mm[0])
            if len(layout.edge_gaps_mm) == 1
            else (
                f"{min(layout.edge_gaps_mm) * mm_to_output:.2f}..{max(layout.edge_gaps_mm) * mm_to_output:.2f} {unit_label}"
                if layout.edge_gaps_mm
                else "—"
            )
        )
        eg_left = eg_waist = eg_right = eg_val
    else:
        sp_left = sp_waist = sp_right = "—"
        eg_left = eg_waist = eg_right = "—"

    sp_col, eg_col = st.columns(2)
    with sp_col:
        st.markdown("**Center spacing**")
        sp_inner = st.columns(3)
        sp_inner[0].metric(f"Top (above {terms['line_lower']})", sp_left)
        sp_inner[1].metric(f"{terms['line']} spacing", sp_waist)
        sp_inner[2].metric(f"Bottom (below {terms['line_lower']})", sp_right)
    with eg_col:
        st.markdown("**Edge-to-edge gap**")
        eg_inner = st.columns(3)
        eg_inner[0].metric(f"Top (above {terms['line_lower']})", eg_left)
        eg_inner[1].metric(f"{terms['line']} gap", eg_waist)
        eg_inner[2].metric(f"Bottom (below {terms['line_lower']})", eg_right)

    if layout.warnings:
        for warning in layout.warnings:
            st.warning(warning)
    else:
        st.success("Layout is feasible with the current settings.")

    st.subheader(f"{terms['item_plural'].capitalize()} center positions")
    if layout.centers_mm:
        if layout.waist_pair_indices is not None and use_closer_waist_pair:
            left_index, right_index = layout.waist_pair_indices
            labels = [
                (
                    f"{terms['line']} {terms['item_singular']} {i - left_index + 1}"
                    if left_index <= i <= right_index
                    else (
                        f"Above {terms['line_lower']}"
                        if i < left_index
                        else f"Below {terms['line_lower']}"
                    )
                )
                for i in range(len(layout.centers_mm))
            ]
        else:
            labels = ["Standard"] * len(layout.centers_mm)

        spacing_to_next = [
            (
                round(layout.center_spacings_mm[i], 3)
                if i < len(layout.center_spacings_mm)
                else None
            )
            for i in range(len(layout.centers_mm))
        ]
        edge_gap_to_next = [
            round(layout.edge_gaps_mm[i], 3) if i < len(layout.edge_gaps_mm) else None
            for i in range(len(layout.centers_mm))
        ]

        df = pd.DataFrame(
            {
                f"{terms['item_singular'].capitalize()} #": list(
                    range(1, len(layout.centers_mm) + 1)
                ),
                f"Center from strip start ({unit_label})": [
                    round(v * mm_to_output, 3) for v in layout.centers_mm
                ],
                "Type": labels,
                f"Center spacing to next ({unit_label})": [
                    round(v * mm_to_output, 3) if v is not None else None
                    for v in spacing_to_next
                ],
                f"Edge gap to next ({unit_label})": [
                    round(v * mm_to_output, 3) if v is not None else None
                    for v in edge_gap_to_next
                ],
            }
        )
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No center positions to display for this configuration.")

    st.subheader("Printable export (Letter)")
    printable_svg, printable_scale, printable_orientation = build_printable_svg_letter(
        length_mm=length_mm,
        margin_top_mm=margin_top_mm,
        margin_bottom_mm=margin_bottom_mm,
        radius_mm=radius_mm,
        layout=layout,
        use_closer_waist_pair=use_closer_waist_pair,
        count=count,
        waist_edge_gap_mm=waist_edge_gap_mm,
        planner_mode=planner_mode,
        item_plural=terms["item_plural"],
        line_label=terms["line"],
        buttonhole_flip_90=effective_buttonhole_flip_90,
        buttonhole_flip_last_90=effective_buttonhole_flip_last_90,
    )
    st.download_button(
        "Download SVG (100% scale)",
        data=printable_svg,
        file_name=(
            "buttonhole_template_full_scale.svg"
            if planner_mode == MODE_BUTTONHOLES
            else "grommet_template_full_scale.svg"
        ),
        mime="image/svg+xml",
        use_container_width=True,
    )

    if REPORTLAB_AVAILABLE:
        printable_pdf, pdf_page_count = build_printable_pdf_letter(
            length_mm=length_mm,
            margin_top_mm=margin_top_mm,
            margin_bottom_mm=margin_bottom_mm,
            radius_mm=radius_mm,
            layout=layout,
            use_closer_waist_pair=use_closer_waist_pair,
            count=count,
            waist_edge_gap_mm=waist_edge_gap_mm,
            planner_mode=planner_mode,
            item_plural=terms["item_plural"],
            line_label=terms["line"],
            buttonhole_flip_90=effective_buttonhole_flip_90,
            buttonhole_flip_last_90=effective_buttonhole_flip_last_90,
        )
        st.download_button(
            "Download PDF Letter (100% scale, multi-page)",
            data=printable_pdf,
            file_name=(
                "buttonhole_template_letter.pdf"
                if planner_mode == MODE_BUTTONHOLES
                else "grommet_template_letter.pdf"
            ),
            mime="application/pdf",
            use_container_width=True,
        )
        st.caption(
            f"PDF export uses Letter landscape at 100% scale and spans {pdf_page_count} page(s)."
        )
    else:
        st.caption(
            "PDF export is unavailable because reportlab is not installed. SVG export is ready to print."
        )

    st.caption(
        f"SVG export mode: {printable_orientation}. Drawing scale: {printable_scale * 100:.2f}%."
    )

    st.subheader("Help")
    st.markdown(
        "- Documentation and source code: https://github.com/adumont/grommet-planner"
    )
    st.markdown(
        "- Suggestions or feedback: [@sewing.alex](https://www.instagram.com/sewing.alex)"
    )
    st.caption("License: GPL-3.0-only. This project is free to use.")


if __name__ == "__main__":
    main()
