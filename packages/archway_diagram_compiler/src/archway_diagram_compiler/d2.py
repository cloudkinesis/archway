"""Compatibility wrapper for D2 generation.

New code should render from LayoutModel via d2_backend. This module remains so
older callers of generate_d2(spec) still work without owning layout decisions.
"""

from typing import Dict, Optional

from archway_diagram_compiler.d2_backend import render_layout_model_to_d2
from archway_diagram_compiler.layout_ir import build_layout_model_from_view
from archway_diagram_compiler.models import SemanticArchitectureSpec


def generate_d2(spec: SemanticArchitectureSpec, icon_paths: Optional[Dict[str, str]] = None) -> str:
    return render_layout_model_to_d2(build_layout_model_from_view(spec), icon_paths=icon_paths)
