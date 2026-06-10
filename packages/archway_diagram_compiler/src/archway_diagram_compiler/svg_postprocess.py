"""Safe SVG post-processing hooks.

These functions are generic renderer cleanups. They do not inspect node ids,
labels, or D2-internal class names beyond the public ``connection`` path class
that identifies edge geometry in D2 SVG output.
"""

from pathlib import Path
import re


def orthogonalize_connection_paths(svg_path: Path, threshold: float = 1.0) -> int:
    if not svg_path.exists():
        return 0
    text = svg_path.read_text(encoding="utf-8", errors="ignore")
    rewrites = 0

    def replace_path(match: re.Match) -> str:
        nonlocal rewrites
        prefix, path_data, suffix = match.groups()
        updated = _orthogonal_path_data(path_data, threshold=threshold)
        if updated == path_data:
            return match.group(0)
        rewrites += 1
        return f'{prefix}{updated}{suffix}'

    updated_text = re.sub(
        r'(<path d=")([^"]+)("[^>]*class="connection"[^>]*>)',
        replace_path,
        text,
    )
    if rewrites:
        svg_path.write_text(updated_text, encoding="utf-8")
    return rewrites


def move_network_header_labels(svg_path: Path) -> int:
    return 0


def _orthogonal_path_data(path_data: str, threshold: float) -> str:
    tokens = re.findall(r"([ML])\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)", path_data)
    if len(tokens) < 2:
        return path_data
    points = [(command, float(x), float(y)) for command, x, y in tokens]
    output = [_format_point(points[0][0], points[0][1], points[0][2])]
    changed = False
    previous_x = points[0][1]
    previous_y = points[0][2]
    for command, x, y in points[1:]:
        if abs(x - previous_x) > threshold and abs(y - previous_y) > threshold:
            midpoint_x = previous_x + ((x - previous_x) / 2)
            output.append(_format_point("L", midpoint_x, previous_y))
            output.append(_format_point("L", midpoint_x, y))
            changed = True
        output.append(_format_point(command, x, y))
        previous_x = x
        previous_y = y
    if not changed:
        return path_data
    return " ".join(output)


def _format_point(command: str, x: float, y: float) -> str:
    return f"{command} {x:.6f} {y:.6f}"
