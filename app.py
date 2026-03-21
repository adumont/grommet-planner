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


def _build_spacing_lists(centers_mm: list[float], radius_mm: float) -> tuple[list[float], list[float], float | None]:
    center_spacings = [centers_mm[i + 1] - centers_mm[i] for i in range(len(centers_mm) - 1)]
    edge_gaps = [spacing - (2 * radius_mm) for spacing in center_spacings]

    if not center_spacings:
        return center_spacings, edge_gaps, None

    first_spacing = center_spacings[0]
    is_uniform = all(abs(spacing - first_spacing) < 1e-9 for spacing in center_spacings)
    return center_spacings, edge_gaps, (first_spacing if is_uniform else None)


def _find_standard_pair_index(layout: GrommetLayout, use_closer_waist_pair: bool) -> int | None:
    if len(layout.centers_mm) < 2:
        return None

    for pair_index in range(len(layout.centers_mm) - 1):
        is_waist_pair = (
            use_closer_waist_pair
            and layout.waist_pair_indices is not None
            and pair_index == layout.waist_pair_indices[0]
        )
        if not is_waist_pair:
            return pair_index
    return None


def _letter_landscape_layout(length_mm: float) -> tuple[float, float, float, float, int]:
    page_w = 279.4
    page_h = 215.9
    margin_mm = 10.0
    usable_w = page_w - (2 * margin_mm)
    page_count = max(1, int(-(-length_mm // usable_w)))
    return page_w, page_h, margin_mm, usable_w, page_count


def build_printable_svg_letter(
    length_mm: float,
    margin_mm: float,
    radius_mm: float,
    layout: GrommetLayout,
    use_closer_waist_pair: bool,
) -> tuple[str, float, str]:
    page_margin = 10.0
    page_w = length_mm + (2 * page_margin)
    page_h = 120.0
    scale = 1.0
    start_x = page_margin
    orientation = "Full-width SVG"
    strip_y = 28.0
    strip_h = max(18.0, (2 * radius_mm * scale) + 8.0)
    center_y = strip_y + (strip_h / 2)

    def x_pos(value_mm: float) -> float:
        return start_x + value_mm * scale

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{page_w}mm" height="{page_h}mm" viewBox="0 0 {page_w} {page_h}">',
        f'<rect x="0.5" y="0.5" width="{page_w - 1}" height="{page_h - 1}" fill="white" stroke="#d4d4d8" stroke-width="0.5"/>',
        f'<text x="{page_margin}" y="10" font-size="6" fill="#18181b">Grommet template (full scale SVG)</text>',
        f'<text x="{page_margin}" y="16" font-size="5" fill="#18181b">Print setting: Actual size / 100%. Drawing scale: {scale * 100:.2f}%</text>',
        f'<rect x="{x_pos(0)}" y="{strip_y}" width="{length_mm * scale}" height="{strip_h}" fill="#ffffff" stroke="#111827" stroke-width="0.6"/>',
        f'<line x1="{x_pos(0)}" y1="{strip_y + strip_h + 6}" x2="{x_pos(length_mm)}" y2="{strip_y + strip_h + 6}" stroke="#111827" stroke-width="0.4"/>',
        f'<text x="{(x_pos(0) + x_pos(length_mm)) / 2}" y="{strip_y + strip_h + 11}" text-anchor="middle" font-size="4.5" fill="#111827">Total length: {length_mm:.2f} mm</text>',
        f'<line x1="{x_pos(0)}" y1="{strip_y - 5}" x2="{x_pos(margin_mm)}" y2="{strip_y - 5}" stroke="#0369a1" stroke-width="0.5"/>',
        f'<line x1="{x_pos(length_mm - margin_mm)}" y1="{strip_y - 5}" x2="{x_pos(length_mm)}" y2="{strip_y - 5}" stroke="#0369a1" stroke-width="0.5"/>',
    ]

    waist_left = waist_right = None
    if layout.waist_pair_indices is not None and layout.waist_pair_indices[1] < len(layout.centers_mm):
        waist_left = layout.centers_mm[layout.waist_pair_indices[0]]
        waist_right = layout.centers_mm[layout.waist_pair_indices[1]]

    svg.append(
        f'<line x1="{x_pos(0)}" y1="{center_y}" x2="{x_pos(length_mm)}" y2="{center_y}" stroke="#94a3b8" stroke-width="0.3" stroke-dasharray="2 1"/>'
    )

    for index, center in enumerate(layout.centers_mm):
        is_waist = use_closer_waist_pair and layout.waist_pair_indices is not None and index in layout.waist_pair_indices
        stroke = "#c2410c" if is_waist else "#1f2937"
        fill = "#fff7ed" if is_waist else "#ffffff"
        svg.extend(
            [
                f'<circle cx="{x_pos(center)}" cy="{center_y}" r="{max(0.8, radius_mm * scale)}" fill="{fill}" stroke="{stroke}" stroke-width="0.5"/>',
                f'<line x1="{x_pos(center)}" y1="{strip_y - 1}" x2="{x_pos(center)}" y2="{strip_y + strip_h + 1}" stroke="{stroke}" stroke-width="0.35" stroke-dasharray="1.2 1.2"/>',
            ]
        )

    waist_x = layout.waist_position_mm
    if 0 <= waist_x <= length_mm:
        svg.extend(
            [
                f'<line x1="{x_pos(waist_x)}" y1="{strip_y - 7}" x2="{x_pos(waist_x)}" y2="{strip_y + strip_h + 7}" stroke="#b91c1c" stroke-width="0.45" stroke-dasharray="1.5 1.5"/>',
                f'<text x="{x_pos(waist_x)}" y="{strip_y + strip_h + 18}" text-anchor="middle" font-size="4.3" fill="#b91c1c">Waist: {waist_x:.2f} mm</text>',
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
                f'<text x="{(x_pos(c1) + x_pos(c2)) / 2}" y="{y_c2c - 3}" text-anchor="middle" font-size="4.2" fill="#166534">Standard center-to-center: {c2c:.2f} mm</text>',
                f'<line x1="{x_pos(c1 + radius_mm)}" y1="{y_gap}" x2="{x_pos(c2 - radius_mm)}" y2="{y_gap}" stroke="#0f766e" stroke-width="0.55"/>',
                f'<line x1="{x_pos(c1 + radius_mm)}" y1="{y_gap - 2}" x2="{x_pos(c1 + radius_mm)}" y2="{y_gap + 2}" stroke="#0f766e" stroke-width="0.4"/>',
                f'<line x1="{x_pos(c2 - radius_mm)}" y1="{y_gap - 2}" x2="{x_pos(c2 - radius_mm)}" y2="{y_gap + 2}" stroke="#0f766e" stroke-width="0.4"/>',
                f'<text x="{(x_pos(c1) + x_pos(c2)) / 2}" y="{y_gap - 3}" text-anchor="middle" font-size="4.2" fill="#0f766e">Standard edge gap: {edge_gap:.2f} mm</text>',
            ]
        )

    if use_closer_waist_pair and waist_left is not None and waist_right is not None:
        waist_c2c = waist_right - waist_left
        y_waist_top = strip_y + 5
        y_waist_gap = strip_y + strip_h + 44
        svg.extend(
            [
                f'<line x1="{x_pos(waist_left)}" y1="{y_waist_top}" x2="{x_pos(waist_right)}" y2="{y_waist_top}" stroke="#b45309" stroke-width="0.55"/>',
                f'<line x1="{x_pos(waist_left)}" y1="{y_waist_top - 2}" x2="{x_pos(waist_left)}" y2="{y_waist_top + 2}" stroke="#b45309" stroke-width="0.4"/>',
                f'<line x1="{x_pos(waist_right)}" y1="{y_waist_top - 2}" x2="{x_pos(waist_right)}" y2="{y_waist_top + 2}" stroke="#b45309" stroke-width="0.4"/>',
                f'<text x="{(x_pos(waist_left) + x_pos(waist_right)) / 2}" y="{y_waist_top - 3}" text-anchor="middle" font-size="4.2" fill="#92400e">Waist center-to-center: {waist_c2c:.2f} mm</text>',
                f'<line x1="{x_pos(waist_left + radius_mm)}" y1="{y_waist_gap}" x2="{x_pos(waist_right - radius_mm)}" y2="{y_waist_gap}" stroke="#ea580c" stroke-width="0.55"/>',
                f'<line x1="{x_pos(waist_left + radius_mm)}" y1="{y_waist_gap - 2}" x2="{x_pos(waist_left + radius_mm)}" y2="{y_waist_gap + 2}" stroke="#ea580c" stroke-width="0.4"/>',
                f'<line x1="{x_pos(waist_right - radius_mm)}" y1="{y_waist_gap - 2}" x2="{x_pos(waist_right - radius_mm)}" y2="{y_waist_gap + 2}" stroke="#ea580c" stroke-width="0.4"/>',
                f'<text x="{(x_pos(waist_left) + x_pos(waist_right)) / 2}" y="{y_waist_gap - 3}" text-anchor="middle" font-size="4.2" fill="#9a3412">Waist edge gap: {waist_c2c - (2 * radius_mm):.2f} mm</text>',
            ]
        )

    centers_text = [f"{idx + 1}:{value:.2f}" for idx, value in enumerate(layout.centers_mm)]
    chunk_size = 10
    base_y = strip_y + strip_h + 58
    for line_index in range(0, len(centers_text), chunk_size):
        chunk = centers_text[line_index : line_index + chunk_size]
        svg.append(
            f'<text x="{page_margin}" y="{base_y + (line_index // chunk_size) * 6}" font-size="4.1" fill="#18181b">Centers (mm) {", ".join(chunk)}</text>'
        )

    svg.append("</svg>")
    return "\n".join(svg), scale, orientation


def build_printable_pdf_letter(
    length_mm: float,
    margin_mm: float,
    radius_mm: float,
    layout: GrommetLayout,
    use_closer_waist_pair: bool,
) -> tuple[bytes, int]:
    if not REPORTLAB_AVAILABLE or RL_pagesizes is None or RL_units is None or RL_canvas_module is None:
        raise RuntimeError("PDF export requested but reportlab is not available.")

    page_w, page_h, page_margin, usable_w, page_count = _letter_landscape_layout(length_mm)
    scale = 1.0
    page_size = RL_pagesizes.landscape(RL_pagesizes.LETTER)
    buffer = io.BytesIO()
    pdf = RL_canvas_module.Canvas(buffer, pagesize=page_size)

    strip_y = 40.0
    strip_h = max(18.0, (2 * radius_mm * scale) + 8.0)
    center_y = strip_y + (strip_h / 2)

    def mm_to_pt(value_mm: float) -> float:
        return value_mm * RL_units.mm

    def x_local(global_mm: float, segment_start_mm: float) -> float:
        return page_margin + (global_mm - segment_start_mm)

    for page_index in range(page_count):
        segment_start = page_index * usable_w
        segment_end = min(length_mm, segment_start + usable_w)
        segment_width = segment_end - segment_start

        pdf.setFont("Helvetica", 8)
        pdf.drawString(mm_to_pt(10), mm_to_pt(page_h - 12), "Grommet template Letter landscape - print at 100% / actual size")
        pdf.drawString(
            mm_to_pt(10),
            mm_to_pt(page_h - 17),
            f"Page {page_index + 1}/{page_count} | Segment {segment_start:.2f}..{segment_end:.2f} mm | Scale 100%",
        )

        pdf.setLineWidth(0.8)
        pdf.rect(mm_to_pt(page_margin), mm_to_pt(page_h - (strip_y + strip_h)), mm_to_pt(segment_width), mm_to_pt(strip_h))

        left_boundary_label = f"X={segment_start:.2f}"
        right_boundary_label = f"X={segment_end:.2f}"
        pdf.setFont("Helvetica", 6)
        pdf.drawString(mm_to_pt(page_margin), mm_to_pt(page_h - (strip_y + strip_h + 4)), left_boundary_label)
        pdf.drawRightString(mm_to_pt(page_margin + segment_width), mm_to_pt(page_h - (strip_y + strip_h + 4)), right_boundary_label)

        local_margin_left = margin_mm
        if segment_start <= local_margin_left <= segment_end:
            x = x_local(local_margin_left, segment_start)
            pdf.setDash(1.5, 1.5)
            pdf.line(mm_to_pt(x), mm_to_pt(page_h - (strip_y - 3)), mm_to_pt(x), mm_to_pt(page_h - (strip_y + strip_h + 3)))
            pdf.setDash()

        local_margin_right = length_mm - margin_mm
        if segment_start <= local_margin_right <= segment_end:
            x = x_local(local_margin_right, segment_start)
            pdf.setDash(1.5, 1.5)
            pdf.line(mm_to_pt(x), mm_to_pt(page_h - (strip_y - 3)), mm_to_pt(x), mm_to_pt(page_h - (strip_y + strip_h + 3)))
            pdf.setDash()

        if segment_start <= layout.waist_position_mm <= segment_end:
            x = x_local(layout.waist_position_mm, segment_start)
            pdf.setDash(2, 2)
            pdf.line(mm_to_pt(x), mm_to_pt(page_h - (strip_y - 4)), mm_to_pt(x), mm_to_pt(page_h - (strip_y + strip_h + 4)))
            pdf.setDash()

        pdf.setLineWidth(0.3)
        pdf.setDash(2, 1)
        pdf.line(mm_to_pt(page_margin), mm_to_pt(page_h - center_y), mm_to_pt(page_margin + segment_width), mm_to_pt(page_h - center_y))
        pdf.setDash()

        for center in layout.centers_mm:
            if (center + radius_mm) < segment_start or (center - radius_mm) > segment_end:
                continue
            x_center = x_local(center, segment_start)
            pdf.circle(mm_to_pt(x_center), mm_to_pt(page_h - center_y), mm_to_pt(max(0.8, radius_mm)), stroke=1, fill=0)
            pdf.setDash(1.5, 1.5)
            pdf.line(mm_to_pt(x_center), mm_to_pt(page_h - (strip_y - 1)), mm_to_pt(x_center), mm_to_pt(page_h - (strip_y + strip_h + 1)))
            pdf.setDash()

        if page_index < (page_count - 1):
            pdf.setDash(2, 2)
            pdf.line(mm_to_pt(page_margin + segment_width), mm_to_pt(page_h - (strip_y - 10)), mm_to_pt(page_margin + segment_width), mm_to_pt(page_h - (strip_y + strip_h + 10)))
            pdf.setDash()
            pdf.drawString(mm_to_pt(page_margin + segment_width - 32), mm_to_pt(page_h - (strip_y + strip_h + 12)), "Join next page here")

        pdf.setFont("Helvetica", 6)
        pdf.drawString(mm_to_pt(10), mm_to_pt(page_h - (strip_y + strip_h + 14)), f"Total length: {length_mm:.2f} mm   Margin: {margin_mm:.2f} mm")
        centers_on_page = [f"{idx + 1}:{v:.2f}" for idx, v in enumerate(layout.centers_mm) if segment_start <= v <= segment_end]
        if centers_on_page:
            pdf.drawString(
                mm_to_pt(10),
                mm_to_pt(page_h - (strip_y + strip_h + 19)),
                f"Centers on this page (mm): {', '.join(centers_on_page[:12])}",
            )

        pdf.showPage()

    pdf.save()
    return buffer.getvalue(), page_count


def calculate_layout(
    length_mm: float,
    margin_mm: float,
    radius_mm: float,
    count: int,
    use_closer_waist_pair: bool,
    waist_position_mm: float,
    waist_edge_gap_mm: float,
) -> GrommetLayout:
    warnings: list[str] = []
    start_center = margin_mm + radius_mm
    end_center = length_mm - margin_mm - radius_mm

    if end_center - start_center < 0:
        warnings.append("Margins + grommet size exceed strip length. Reduce margin/diameter or increase strip length.")
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
        if center - radius_mm < margin_mm or center + radius_mm > (length_mm - margin_mm):
            warnings.append("Single grommet does not fit inside strip with the selected margins/diameter.")
        center_spacings, edge_gaps, uniform_spacing = _build_spacing_lists([center], radius_mm)
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
        center_spacings, edge_gaps, uniform_spacing = _build_spacing_lists(centers, radius_mm)
        if edge_gaps and min(edge_gaps) < 0:
            warnings.append("Grommets overlap with current settings (negative edge-to-edge gap).")

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

    if count < 2:
        warnings.append("Closer waist pair requires at least 2 grommets.")
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
    left_waist_center = waist_position_mm - (waist_center_spacing / 2)
    right_waist_center = waist_position_mm + (waist_center_spacing / 2)

    if left_waist_center < start_center or right_waist_center > end_center:
        warnings.append(
            "Waist pair does not fit between margins. Reduce waist gap/radius, move waist, or increase strip length."
        )
    if left_waist_center >= right_waist_center:
        warnings.append("Invalid waist pair geometry.")

    remaining_count = count - 2
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
            warnings.append("No space for left-side grommets before the waist pair.")
        centers.extend(start_center + i * step_left for i in range(left_count))

    centers.append(left_waist_center)
    centers.append(right_waist_center)

    if right_count > 0:
        step_right = (end_center - right_waist_center) / right_count
        if step_right <= 0:
            warnings.append("No space for right-side grommets after the waist pair.")
        centers.extend(right_waist_center + j * step_right for j in range(1, right_count + 1))

    if any(centers[i + 1] <= centers[i] for i in range(len(centers) - 1)):
        warnings.append("Computed centers are not strictly increasing. Check waist position and gap values.")

    center_spacings, edge_gaps, uniform_spacing = _build_spacing_lists(centers, radius_mm)
    if edge_gaps and min(edge_gaps) < 0:
        warnings.append("Grommets overlap with current settings (negative edge-to-edge gap).")

    return GrommetLayout(
        centers_mm=centers,
        center_spacings_mm=center_spacings,
        edge_gaps_mm=edge_gaps,
        uniform_center_spacing_mm=uniform_spacing,
        start_center_mm=centers[0] if centers else start_center,
        end_center_mm=centers[-1] if centers else end_center,
        waist_position_mm=waist_position_mm,
        waist_pair_indices=(left_count, left_count + 1),
        warnings=warnings,
    )


def build_svg(
    length_mm: float,
    margin_mm: float,
    radius_mm: float,
    layout: GrommetLayout,
    use_closer_waist_pair: bool,
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

    rect_x = x_mm(0)
    rect_y = pad_y
    rect_w = x_mm(length_mm) - x_mm(0)

    svg = [
        f'<svg viewBox="0 0 {view_w} {view_h}" width="100%" xmlns="http://www.w3.org/2000/svg">',
        f'<rect x="{rect_x}" y="{rect_y}" width="{rect_w}" height="{strip_h_px}" fill="#f4f4f5" stroke="#3f3f46" stroke-width="1.5"/>',
        f'<line x1="{x_mm(0)}" y1="{rect_y + strip_h_px + 40}" x2="{x_mm(length_mm)}" y2="{rect_y + strip_h_px + 40}" stroke="#3f3f46" stroke-width="1"/>',
        f'<line x1="{x_mm(0)}" y1="{rect_y + strip_h_px + 34}" x2="{x_mm(0)}" y2="{rect_y + strip_h_px + 46}" stroke="#3f3f46" stroke-width="1"/>',
        f'<line x1="{x_mm(length_mm)}" y1="{rect_y + strip_h_px + 34}" x2="{x_mm(length_mm)}" y2="{rect_y + strip_h_px + 46}" stroke="#3f3f46" stroke-width="1"/>',
        f'<text x="{(x_mm(0) + x_mm(length_mm)) / 2}" y="{rect_y + strip_h_px + 62}" text-anchor="middle" font-size="14" fill="#18181b">Total length: {length_mm:.2f} mm</text>',
    ]

    margin_y = rect_y - 10
    svg.extend(
        [
            f'<line x1="{x_mm(0)}" y1="{margin_y}" x2="{x_mm(margin_mm)}" y2="{margin_y}" stroke="#0ea5e9" stroke-width="1.5"/>',
            f'<line x1="{x_mm(length_mm - margin_mm)}" y1="{margin_y}" x2="{x_mm(length_mm)}" y2="{margin_y}" stroke="#0ea5e9" stroke-width="1.5"/>',
            f'<text x="{(x_mm(0) + x_mm(margin_mm)) / 2}" y="{margin_y - 6}" text-anchor="middle" font-size="12" fill="#0369a1">Margin: {margin_mm:.2f} mm</text>',
            f'<text x="{(x_mm(length_mm - margin_mm) + x_mm(length_mm)) / 2}" y="{margin_y - 6}" text-anchor="middle" font-size="12" fill="#0369a1">Margin: {margin_mm:.2f} mm</text>',
        ]
    )

    waist_x_mm = layout.waist_position_mm
    if 0 <= waist_x_mm <= length_mm:
        svg.extend(
            [
                f'<line x1="{x_mm(waist_x_mm)}" y1="{rect_y - 2}" x2="{x_mm(waist_x_mm)}" y2="{rect_y + strip_h_px + 2}" stroke="#dc2626" stroke-dasharray="4 4" stroke-width="1.5"/>',
                f'<text x="{x_mm(waist_x_mm)}" y="{rect_y + strip_h_px + 16}" text-anchor="middle" font-size="12" fill="#b91c1c">Waist: {waist_x_mm:.2f} mm</text>',
            ]
        )

    waist_left = waist_right = None
    if (
        layout.waist_pair_indices is not None
        and layout.waist_pair_indices[1] < len(layout.centers_mm)
    ):
        waist_left = layout.centers_mm[layout.waist_pair_indices[0]]
        waist_right = layout.centers_mm[layout.waist_pair_indices[1]]

    for index, center in enumerate(layout.centers_mm):
        is_waist_pair = (
            layout.waist_pair_indices is not None
            and index in layout.waist_pair_indices
            and use_closer_waist_pair
        )
        fill = "#fdba74" if is_waist_pair else "#bfdbfe"
        stroke = "#c2410c" if is_waist_pair else "#1d4ed8"
        svg.extend(
            [
                f'<circle cx="{x_mm(center)}" cy="{center_y}" r="{radius_mm * scale_x}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>',
                f'<line x1="{x_mm(center)}" y1="{rect_y}" x2="{x_mm(center)}" y2="{rect_y + strip_h_px}" stroke="{stroke}" stroke-dasharray="3 3" stroke-width="1"/>',
            ]
        )

    standard_pair_index = _find_standard_pair_index(layout, use_closer_waist_pair)

    if standard_pair_index is not None:
        c1 = layout.centers_mm[standard_pair_index]
        c2 = layout.centers_mm[standard_pair_index + 1]
        center_to_center = c2 - c1
        standard_edge_gap = center_to_center - (2 * radius_mm)

        y_dim_c2c = rect_y + strip_h_px + 28
        y_dim_gap = rect_y + strip_h_px + 62
        svg.extend(
            [
                f'<line x1="{x_mm(c1)}" y1="{y_dim_c2c}" x2="{x_mm(c2)}" y2="{y_dim_c2c}" stroke="#16a34a" stroke-width="1.5"/>',
                f'<line x1="{x_mm(c1)}" y1="{y_dim_c2c - 5}" x2="{x_mm(c1)}" y2="{y_dim_c2c + 5}" stroke="#16a34a" stroke-width="1"/>',
                f'<line x1="{x_mm(c2)}" y1="{y_dim_c2c - 5}" x2="{x_mm(c2)}" y2="{y_dim_c2c + 5}" stroke="#16a34a" stroke-width="1"/>',
                f'<text x="{(x_mm(c1) + x_mm(c2)) / 2}" y="{y_dim_c2c - 6}" text-anchor="middle" font-size="12" fill="#166534">Standard center-to-center: {center_to_center:.2f} mm</text>',
                f'<line x1="{x_mm(c1 + radius_mm)}" y1="{y_dim_gap}" x2="{x_mm(c2 - radius_mm)}" y2="{y_dim_gap}" stroke="#0f766e" stroke-width="1.5"/>',
                f'<line x1="{x_mm(c1 + radius_mm)}" y1="{y_dim_gap - 5}" x2="{x_mm(c1 + radius_mm)}" y2="{y_dim_gap + 5}" stroke="#0f766e" stroke-width="1"/>',
                f'<line x1="{x_mm(c2 - radius_mm)}" y1="{y_dim_gap - 5}" x2="{x_mm(c2 - radius_mm)}" y2="{y_dim_gap + 5}" stroke="#0f766e" stroke-width="1"/>',
                f'<text x="{(x_mm(c1) + x_mm(c2)) / 2}" y="{y_dim_gap - 6}" text-anchor="middle" font-size="12" fill="#0f766e">Standard edge gap: {standard_edge_gap:.2f} mm</text>',
            ]
        )

    if use_closer_waist_pair and waist_left is not None and waist_right is not None:
        y_c2c_waist = rect_y + 14
        waist_center_to_center = waist_right - waist_left
        svg.extend(
            [
                f'<line x1="{x_mm(waist_left)}" y1="{y_c2c_waist}" x2="{x_mm(waist_right)}" y2="{y_c2c_waist}" stroke="#b45309" stroke-width="1.6"/>',
                f'<line x1="{x_mm(waist_left)}" y1="{y_c2c_waist - 5}" x2="{x_mm(waist_left)}" y2="{y_c2c_waist + 5}" stroke="#b45309" stroke-width="1"/>',
                f'<line x1="{x_mm(waist_right)}" y1="{y_c2c_waist - 5}" x2="{x_mm(waist_right)}" y2="{y_c2c_waist + 5}" stroke="#b45309" stroke-width="1"/>',
                f'<text x="{(x_mm(waist_left) + x_mm(waist_right)) / 2}" y="{y_c2c_waist - 6}" text-anchor="middle" font-size="12" fill="#92400e">Waist center-to-center: {waist_center_to_center:.2f} mm</text>',
            ]
        )

        y_gap = rect_y + strip_h_px + 96
        svg.extend(
            [
                f'<line x1="{x_mm(waist_left + radius_mm)}" y1="{y_gap}" x2="{x_mm(waist_right - radius_mm)}" y2="{y_gap}" stroke="#ea580c" stroke-width="1.6"/>',
                f'<line x1="{x_mm(waist_left + radius_mm)}" y1="{y_gap - 5}" x2="{x_mm(waist_left + radius_mm)}" y2="{y_gap + 5}" stroke="#ea580c" stroke-width="1"/>',
                f'<line x1="{x_mm(waist_right - radius_mm)}" y1="{y_gap - 5}" x2="{x_mm(waist_right - radius_mm)}" y2="{y_gap + 5}" stroke="#ea580c" stroke-width="1"/>',
                f'<text x="{(x_mm(waist_left) + x_mm(waist_right)) / 2}" y="{y_gap - 6}" text-anchor="middle" font-size="12" fill="#9a3412">Waist edge gap: {waist_right - waist_left - (2 * radius_mm):.2f} mm</text>',
            ]
        )

    svg.append("</svg>")
    return "\n".join(svg)


def main() -> None:
    st.set_page_config(page_title="Grommet Strip Planner", layout="wide")
    st.title("Grommet Strip Planner")
    st.write("Plan evenly spaced grommet centers on a strip with end margins.")

    left, right = st.columns([1, 2], gap="large")

    with left:
        length_mm = st.number_input("Strip length (mm)", min_value=1.0, value=350.0, step=1.0)
        margin_mm = st.number_input("End margin each side (mm)", min_value=0.0, value=20.0, step=0.5)
        diameter_mm = st.number_input("Grommet external diameter (mm)", min_value=1, value=9, step=1)
        radius_mm = diameter_mm / 2
        count = st.number_input("Number of grommets", min_value=1, value=6, step=1)
        waist_position_mm = st.number_input(
            "Waist position from strip start (mm)",
            min_value=0.0,
            max_value=float(length_mm),
            value=float(length_mm / 2),
            step=0.5,
        )
        use_closer_waist_pair = st.checkbox("Use closer waist grommet pair", value=False)
        waist_edge_gap_mm = st.number_input(
            "Waist pair edge gap (mm)",
            min_value=0.0,
            value=3.0,
            step=0.5,
            disabled=not use_closer_waist_pair,
            help="Distance between the two waist grommets measured edge-to-edge, centered at the waist.",
        )

    layout = calculate_layout(
        length_mm=length_mm,
        margin_mm=margin_mm,
        radius_mm=radius_mm,
        count=count,
        use_closer_waist_pair=use_closer_waist_pair,
        waist_position_mm=waist_position_mm,
        waist_edge_gap_mm=waist_edge_gap_mm,
    )

    with right:
        st.subheader("Layout diagram")
        components.html(
            build_svg(
                length_mm=length_mm,
                margin_mm=margin_mm,
                radius_mm=radius_mm,
                layout=layout,
                use_closer_waist_pair=use_closer_waist_pair,
            ),
            height=400,
        )

    metric_cols = st.columns(5)
    metric_cols[0].metric("Grommets", f"{count}")
    metric_cols[1].metric("First center", f"{layout.start_center_mm:.2f} mm")
    metric_cols[2].metric("Last center", f"{layout.end_center_mm:.2f} mm")
    metric_cols[3].metric("Waist position", f"{waist_position_mm:.2f} mm")
    metric_cols[4].metric(
        "Center spacing",
        "-"
        if not layout.center_spacings_mm
        else (
            f"{layout.uniform_center_spacing_mm:.2f} mm"
            if layout.uniform_center_spacing_mm is not None
            else f"{min(layout.center_spacings_mm):.2f}..{max(layout.center_spacings_mm):.2f} mm"
        ),
    )

    if layout.edge_gaps_mm:
        if len(layout.edge_gaps_mm) == 1:
            st.metric("Edge-to-edge gap", f"{layout.edge_gaps_mm[0]:.2f} mm")
        else:
            st.metric(
                "Edge-to-edge gaps",
                f"{min(layout.edge_gaps_mm):.2f}..{max(layout.edge_gaps_mm):.2f} mm",
            )

    if layout.warnings:
        for warning in layout.warnings:
            st.warning(warning)
    else:
        st.success("Layout is feasible with the current settings.")

    st.subheader("Grommet center positions")
    if layout.centers_mm:
        labels = ["Standard"] * len(layout.centers_mm)
        if layout.waist_pair_indices is not None and use_closer_waist_pair:
            left_index, right_index = layout.waist_pair_indices
            if left_index < len(labels):
                labels[left_index] = "Waist left"
            if right_index < len(labels):
                labels[right_index] = "Waist right"

        spacing_to_next = [
            round(layout.center_spacings_mm[i], 3) if i < len(layout.center_spacings_mm) else None
            for i in range(len(layout.centers_mm))
        ]
        edge_gap_to_next = [
            round(layout.edge_gaps_mm[i], 3) if i < len(layout.edge_gaps_mm) else None
            for i in range(len(layout.centers_mm))
        ]

        df = pd.DataFrame(
            {
                "Grommet #": list(range(1, len(layout.centers_mm) + 1)),
                "Center from left edge (mm)": [round(v, 3) for v in layout.centers_mm],
                "Type": labels,
                "Center spacing to next (mm)": spacing_to_next,
                "Edge gap to next (mm)": edge_gap_to_next,
            }
        )
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No center positions to display for this configuration.")

    st.subheader("Printable export (Letter)")
    printable_svg, printable_scale, printable_orientation = build_printable_svg_letter(
        length_mm=length_mm,
        margin_mm=margin_mm,
        radius_mm=radius_mm,
        layout=layout,
        use_closer_waist_pair=use_closer_waist_pair,
    )
    st.download_button(
        "Download SVG (100% scale)",
        data=printable_svg,
        file_name="grommet_template_full_scale.svg",
        mime="image/svg+xml",
        use_container_width=True,
    )

    if REPORTLAB_AVAILABLE:
        printable_pdf, pdf_page_count = build_printable_pdf_letter(
            length_mm=length_mm,
            margin_mm=margin_mm,
            radius_mm=radius_mm,
            layout=layout,
            use_closer_waist_pair=use_closer_waist_pair,
        )
        st.download_button(
            "Download PDF Letter (100% scale, multi-page)",
            data=printable_pdf,
            file_name="grommet_template_letter.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
        st.caption(f"PDF export uses Letter landscape at 100% scale and spans {pdf_page_count} page(s).")
    else:
        st.caption("PDF export is unavailable because reportlab is not installed. SVG export is ready to print.")

    st.caption(f"SVG export mode: {printable_orientation}. Drawing scale: {printable_scale * 100:.2f}%.")


if __name__ == "__main__":
    main()