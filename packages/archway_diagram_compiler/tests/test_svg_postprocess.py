from pathlib import Path

from archway_diagram_compiler.svg_postprocess import move_network_header_labels, orthogonalize_connection_paths


def test_svg_postprocess_orthogonalizes_generic_connection_paths(tmp_path):
    svg_path = Path(tmp_path) / "diagram.svg"
    original = (
        '<svg viewBox="0 0 100 100">'
        '<path d="M 10.000000 20.000000 L 90.000000 80.000000" '
        'stroke="#334155" fill="none" class="connection" />'
        "</svg>"
    )
    svg_path.write_text(
        original,
        encoding="utf-8",
    )

    rewrites = orthogonalize_connection_paths(svg_path)

    updated = svg_path.read_text(encoding="utf-8")
    assert rewrites == 1
    assert "L 50.000000 20.000000 L 50.000000 80.000000 L 90.000000 80.000000" in updated


def test_svg_postprocess_does_not_move_labels_by_literal_text(tmp_path):
    svg_path = Path(tmp_path) / "diagram.svg"
    svg_path.write_text(
        '<svg viewBox="0 0 100 100">'
        '<text x="725.000000" y="598.000000" fill="#0A0F25" '
        'class="text fill-N1" style="text-anchor:middle;font-size:24px">APP-VPC</text>'
        '<text x="671.500000" y="635.000000" fill="#0A0F25" '
        'class="text fill-N1" style="text-anchor:middle;font-size:20px">Workloads</text>'
        "</svg>",
        encoding="utf-8",
    )

    rewrites = move_network_header_labels(svg_path)

    updated = svg_path.read_text(encoding="utf-8")
    assert rewrites == 0
    assert 'x="725.000000"' in updated
    assert "text-anchor:middle" in updated
