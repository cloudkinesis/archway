import os
from pathlib import Path

import pytest

from archway_diagram_compiler.renderer import (
    D2Renderer,
    SvgToPngConverter,
    find_d2_executable,
    render_environment,
    svg_viewport,
)


def test_renderer_supports_configurable_executable_timeout_and_format(tmp_path):
    executable = Path(tmp_path) / "fake-d2"
    executable.write_text(
        "#!/bin/sh\n"
        "input=\"\"\n"
        "for arg in \"$@\"; do input=\"$output\"; output=\"$arg\"; done\n"
        "printf 'rendered %s to %s' \"$input\" \"$output\" > \"$output\"\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    source = Path(tmp_path) / "diagram.d2"
    source.write_text("a -> b\n", encoding="utf-8")

    renderer = D2Renderer(executable=str(executable), timeout_seconds=5, layout_engine=None, deterministic_salt=None)
    artifacts, diagnostics = renderer.render(source, tmp_path, formats=("svg",))

    assert diagnostics == []
    assert artifacts["svg"].exists()
    assert artifacts["svg"].read_text(encoding="utf-8").startswith("rendered")


def test_find_d2_executable_discovers_workspace_tool(tmp_path, monkeypatch):
    executable = Path(tmp_path) / ".tools" / "d2" / "d2"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("PATH", "")

    discovered = find_d2_executable(tmp_path)

    assert discovered == executable


def test_render_environment_can_redirect_playwright_cache_for_workspace_tool(tmp_path, monkeypatch):
    executable = Path(tmp_path) / ".tools" / "d2" / "d2"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("ARCHWAY_D2_USE_LOCAL_PLAYWRIGHT", "1")

    env = render_environment(executable)

    assert env["PLAYWRIGHT_DRIVER_PATH"] == str(executable.parent / "playwright-driver")
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(executable.parent / "ms-playwright")
    assert env["XDG_CACHE_HOME"] == str(executable.parent / "cache")


def test_renderer_uses_elk_and_stable_salt_by_default(tmp_path):
    executable = Path(tmp_path) / "fake-d2"
    executable.write_text(
        "#!/bin/sh\n"
        "for arg in \"$@\"; do out=\"$arg\"; done\n"
        "printf '%s\\n' \"$@\" > \"$out\"\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    source = Path(tmp_path) / "diagram.d2"
    source.write_text("a -> b\n", encoding="utf-8")

    renderer = D2Renderer(executable=str(executable), timeout_seconds=5)
    artifacts, diagnostics = renderer.render(source, tmp_path, formats=("svg",))

    assert diagnostics == []
    output = artifacts["svg"].read_text(encoding="utf-8")
    assert "--layout\nelk" in output
    assert "--salt\narchway" in output
    assert "--omit-version" in output


def test_svg_to_png_converter_accepts_timeout_when_png_exists(tmp_path):
    executable = Path(tmp_path) / "fake-browser"
    executable.write_text(
        "#!/bin/sh\n"
        "for arg in \"$@\"; do\n"
        "  case \"$arg\" in\n"
        "    --screenshot=*) out=\"${arg#--screenshot=}\" ;;\n"
        "  esac\n"
        "done\n"
        "printf 'png' > \"$out\"\n"
        "sleep 2\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    svg_path = Path(tmp_path) / "diagram.svg"
    png_path = Path(tmp_path) / "diagram.png"
    svg_path.write_text("<svg></svg>", encoding="utf-8")

    diagnostic = SvgToPngConverter(executable=executable, timeout_seconds=1).convert(svg_path, png_path)

    assert diagnostic is None
    assert png_path.read_text(encoding="utf-8") == "png"


def test_svg_to_png_converter_uses_temp_profile_outside_artifacts(tmp_path):
    executable = Path(tmp_path) / "fake-browser"
    executable.write_text(
        "#!/bin/sh\n"
        "for arg in \"$@\"; do\n"
        "  case \"$arg\" in\n"
        "    --screenshot=*) out=\"${arg#--screenshot=}\" ;;\n"
        "    --user-data-dir=*) profile=\"${arg#--user-data-dir=}\" ;;\n"
        "  esac\n"
        "done\n"
        "printf '%s' \"$profile\" > \"$out\"\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    svg_path = Path(tmp_path) / "diagram.svg"
    png_path = Path(tmp_path) / "view" / "diagram.png"
    svg_path.write_text("<svg></svg>", encoding="utf-8")

    diagnostic = SvgToPngConverter(executable=executable, timeout_seconds=2).convert(svg_path, png_path)

    assert diagnostic is None
    assert ".chrome-profile" not in {path.name for path in png_path.parent.iterdir()}
    assert not png_path.read_text(encoding="utf-8").startswith(str(png_path.parent))


def test_svg_to_png_converter_derives_viewport_from_svg_viewbox(tmp_path):
    svg_path = Path(tmp_path) / "diagram.svg"
    svg_path.write_text('<svg viewBox="0 0 1627 1904"></svg>', encoding="utf-8")

    assert svg_viewport(svg_path) == (1627, 1904)


def test_svg_to_png_converter_scales_large_viewport(tmp_path):
    svg_path = Path(tmp_path) / "diagram.svg"
    svg_path.write_text('<svg viewBox="0 0 4200 2100"></svg>', encoding="utf-8")

    assert svg_viewport(svg_path, max_dimension=2100) == (2100, 1050)


def test_real_d2_renderer_outputs_svg_and_png(tmp_path):
    executable = find_d2_executable(Path.cwd())
    if executable is None:
        pytest.skip("D2 executable is not installed")
    if not os.environ.get("ARCHWAY_RUN_D2_PNG_INTEGRATION"):
        pytest.skip("Set ARCHWAY_RUN_D2_PNG_INTEGRATION=1 to run browser-backed PNG rendering")

    source = Path(tmp_path) / "diagram.d2"
    source.write_text("a -> b\n", encoding="utf-8")

    renderer = D2Renderer(executable=executable, timeout_seconds=30)
    artifacts, diagnostics = renderer.render(source, tmp_path, formats=("svg", "png"))

    assert diagnostics == []
    assert artifacts["svg"].exists()
    assert artifacts["svg"].stat().st_size > 0
    assert artifacts["png"].exists()
    assert artifacts["png"].stat().st_size > 0
