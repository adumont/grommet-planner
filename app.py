from dataclasses import dataclass

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


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

    standard_pair_index = None
    if len(layout.centers_mm) >= 2:
        for pair_index in range(len(layout.centers_mm) - 1):
            is_waist_pair = (
                use_closer_waist_pair
                and layout.waist_pair_indices is not None
                and pair_index == layout.waist_pair_indices[0]
            )
            if not is_waist_pair:
                standard_pair_index = pair_index
                break

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


if __name__ == "__main__":
    main()