from dataclasses import dataclass

import pandas as pd
import streamlit as st


@dataclass
class GrommetLayout:
    centers_mm: list[float]
    center_spacing_mm: float | None
    edge_gap_mm: float | None
    start_center_mm: float
    end_center_mm: float
    warnings: list[str]


def calculate_layout(length_mm: float, margin_mm: float, radius_mm: float, count: int) -> GrommetLayout:
    warnings: list[str] = []
    start_center = margin_mm + radius_mm
    end_center = length_mm - margin_mm - radius_mm

    if count == 1:
        center = length_mm / 2
        if center - radius_mm < margin_mm or center + radius_mm > (length_mm - margin_mm):
            warnings.append("Single grommet does not fit inside strip with the selected margins/radius.")
        return GrommetLayout(
            centers_mm=[center],
            center_spacing_mm=None,
            edge_gap_mm=None,
            start_center_mm=center,
            end_center_mm=center,
            warnings=warnings,
        )

    span_for_centers = end_center - start_center
    if span_for_centers < 0:
        warnings.append("Margins + radii exceed strip length. Reduce margin/radius or increase strip length.")
        return GrommetLayout(
            centers_mm=[],
            center_spacing_mm=None,
            edge_gap_mm=None,
            start_center_mm=start_center,
            end_center_mm=end_center,
            warnings=warnings,
        )

    center_spacing = span_for_centers / (count - 1)
    edge_gap = center_spacing - 2 * radius_mm
    if edge_gap < 0:
        warnings.append("Grommets overlap with current settings (negative edge-to-edge gap).")

    centers = [start_center + i * center_spacing for i in range(count)]
    return GrommetLayout(
        centers_mm=centers,
        center_spacing_mm=center_spacing,
        edge_gap_mm=edge_gap,
        start_center_mm=start_center,
        end_center_mm=end_center,
        warnings=warnings,
    )


def build_svg(length_mm: float, margin_mm: float, radius_mm: float, layout: GrommetLayout) -> str:
    width_px = 1000
    strip_h_px = 120
    pad_x = 40
    pad_y = 30
    view_w = width_px + pad_x * 2
    view_h = 260

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

    for center in layout.centers_mm:
        svg.extend(
            [
                f'<circle cx="{x_mm(center)}" cy="{center_y}" r="{radius_mm * scale_x}" fill="#bfdbfe" stroke="#1d4ed8" stroke-width="1.5"/>',
                f'<line x1="{x_mm(center)}" y1="{rect_y}" x2="{x_mm(center)}" y2="{rect_y + strip_h_px}" stroke="#1d4ed8" stroke-dasharray="3 3" stroke-width="1"/>',
            ]
        )

    if layout.center_spacing_mm is not None and len(layout.centers_mm) >= 2:
        c1 = layout.centers_mm[0]
        c2 = layout.centers_mm[1]
        y_dim = rect_y + strip_h_px + 18
        svg.extend(
            [
                f'<line x1="{x_mm(c1)}" y1="{y_dim}" x2="{x_mm(c2)}" y2="{y_dim}" stroke="#16a34a" stroke-width="1.5"/>',
                f'<line x1="{x_mm(c1)}" y1="{y_dim - 5}" x2="{x_mm(c1)}" y2="{y_dim + 5}" stroke="#16a34a" stroke-width="1"/>',
                f'<line x1="{x_mm(c2)}" y1="{y_dim - 5}" x2="{x_mm(c2)}" y2="{y_dim + 5}" stroke="#16a34a" stroke-width="1"/>',
                f'<text x="{(x_mm(c1) + x_mm(c2)) / 2}" y="{y_dim - 6}" text-anchor="middle" font-size="12" fill="#166534">Center spacing: {layout.center_spacing_mm:.2f} mm</text>',
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
        length_mm = st.number_input("Strip length (mm)", min_value=1.0, value=500.0, step=1.0)
        margin_mm = st.number_input("End margin each side (mm)", min_value=0.0, value=20.0, step=0.5)
        radius_mm = st.number_input("Grommet external radius (mm)", min_value=0.1, value=5.0, step=0.1)
        count = st.slider("Number of grommets", min_value=1, max_value=40, value=6, step=1)

    layout = calculate_layout(length_mm, margin_mm, radius_mm, count)

    with right:
        st.subheader("Layout diagram")
        st.components.v1.html(build_svg(length_mm, margin_mm, radius_mm, layout), height=280)

    metric_cols = st.columns(4)
    metric_cols[0].metric("Grommets", f"{count}")
    metric_cols[1].metric("First center", f"{layout.start_center_mm:.2f} mm")
    metric_cols[2].metric("Last center", f"{layout.end_center_mm:.2f} mm")
    metric_cols[3].metric(
        "Center spacing",
        "-" if layout.center_spacing_mm is None else f"{layout.center_spacing_mm:.2f} mm",
    )

    if layout.edge_gap_mm is not None:
        st.metric("Edge-to-edge gap between adjacent grommets", f"{layout.edge_gap_mm:.2f} mm")

    if layout.warnings:
        for warning in layout.warnings:
            st.warning(warning)
    else:
        st.success("Layout is feasible with the current settings.")

    st.subheader("Grommet center positions")
    if layout.centers_mm:
        df = pd.DataFrame(
            {
                "Grommet #": list(range(1, len(layout.centers_mm) + 1)),
                "Center from left edge (mm)": [round(v, 3) for v in layout.centers_mm],
            }
        )
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No center positions to display for this configuration.")


if __name__ == "__main__":
    main()