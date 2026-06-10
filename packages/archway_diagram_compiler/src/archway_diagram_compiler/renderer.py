"""Subprocess-backed D2 renderer."""

import math
import os
import re
import subprocess
import tempfile
import time
from os import PathLike
from pathlib import Path
from shutil import which
from typing import Iterable, List, Optional, Union

from archway_diagram_compiler.models import Diagnostic


class D2Renderer:
    def __init__(
        self,
        executable: Optional[Union[str, PathLike]] = None,
        timeout_seconds: int = 90,
        layout_engine: Optional[str] = "elk",
        deterministic_salt: Optional[str] = "archway",
    ):
        self.executable = str(executable or find_d2_executable() or "d2")
        self.timeout_seconds = timeout_seconds
        self.layout_engine = layout_engine
        self.deterministic_salt = deterministic_salt

    def render(
        self,
        d2_path: Path,
        output_dir: Path,
        formats: Iterable[str] = ("svg", "png"),
    ) -> tuple:
        artifacts = {}
        diagnostics: List[Diagnostic] = []
        output_dir.mkdir(parents=True, exist_ok=True)

        for output_format in formats:
            if output_format not in {"svg", "png", "pdf"}:
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="unsupported_render_format",
                        message=f"D2 output format is not supported: {output_format}.",
                    )
                )
                continue
            output_path = output_dir / f"{d2_path.stem}.{output_format}"
            command = [self.executable]
            if self.layout_engine:
                command.extend(["--layout", self.layout_engine])
            if self.deterministic_salt:
                command.extend(["--salt", self.deterministic_salt])
            command.extend(["--omit-version", str(d2_path), str(output_path)])
            try:
                subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    env=render_environment(Path(self.executable)),
                )
                artifacts[output_format] = output_path
            except FileNotFoundError:
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="d2_executable_not_found",
                        message=f"D2 executable was not found: {self.executable}.",
                    )
                )
                break
            except subprocess.TimeoutExpired:
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="d2_render_timeout",
                        message=f"D2 render timed out after {self.timeout_seconds} seconds.",
                    )
                )
            except subprocess.CalledProcessError as exc:
                stderr = (exc.stderr or "").strip()
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="d2_render_failed",
                        message=stderr or f"D2 render failed for {output_format}.",
                    )
                )

        return artifacts, diagnostics


def write_d2(d2_text: str, output_dir: Path, stem: str = "diagram") -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    d2_path = output_dir / f"{stem}.d2"
    d2_path.write_text(d2_text, encoding="utf-8")
    return d2_path


class SvgToPngConverter:
    def __init__(
        self,
        executable: Optional[Union[str, PathLike]] = None,
        timeout_seconds: int = 15,
        viewport: Optional[tuple] = None,
        max_viewport_dimension: int = 2400,
    ):
        self.rasterizer = None if executable else find_svg_rasterizer()
        self.executable = str(executable or find_browser_executable() or "")
        self.timeout_seconds = timeout_seconds
        self.viewport = viewport
        self.max_viewport_dimension = max_viewport_dimension

    def convert(self, svg_path: Path, png_path: Path) -> Optional[Diagnostic]:
        if self.rasterizer is not None:
            diagnostic = self._convert_with_rasterizer(svg_path, png_path, self.rasterizer)
            if diagnostic is None:
                return None
        if not self.executable:
            return Diagnostic(
                severity="error",
                code="svg_to_png_converter_not_found",
                message="No browser executable was found for SVG to PNG conversion.",
            )
        png_path.parent.mkdir(parents=True, exist_ok=True)
        viewport = self.viewport or svg_viewport(svg_path, max_dimension=self.max_viewport_dimension)
        try:
            with tempfile.TemporaryDirectory(prefix="archway-chrome-profile-") as profile_dir:
                command = [
                    self.executable,
                    "--headless=new",
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-crash-reporter",
                    "--disable-breakpad",
                    f"--user-data-dir={profile_dir}",
                    f"--screenshot={png_path}",
                    f"--window-size={viewport[0]},{viewport[1]}",
                    svg_path.resolve().as_uri(),
                ]
                subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                )
        except subprocess.TimeoutExpired:
            if _nonempty_file_exists(png_path):
                return None
            return Diagnostic(
                severity="error",
                code="svg_to_png_timeout",
                message=f"SVG to PNG conversion timed out after {self.timeout_seconds} seconds.",
            )
        except subprocess.CalledProcessError as exc:
            if _nonempty_file_exists(png_path):
                return None
            stderr = (exc.stderr or "").strip()
            return Diagnostic(
                severity="error",
                code="svg_to_png_failed",
                message=stderr or "SVG to PNG conversion failed.",
            )
        return None

    def _convert_with_rasterizer(self, svg_path: Path, png_path: Path, rasterizer: Path) -> Optional[Diagnostic]:
        png_path.parent.mkdir(parents=True, exist_ok=True)
        if rasterizer.name == "resvg":
            command = [str(rasterizer), str(svg_path), str(png_path)]
        else:
            command = [str(rasterizer), str(svg_path), "-o", str(png_path)]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            return Diagnostic(
                severity="error",
                code="svg_to_png_timeout",
                message=f"SVG to PNG conversion timed out after {self.timeout_seconds} seconds.",
            )
        except subprocess.CalledProcessError as exc:
            if _nonempty_file_exists(png_path):
                return None
            stderr = (exc.stderr or "").strip()
            return Diagnostic(
                severity="warning",
                code="svg_to_png_rasterizer_failed",
                message=stderr or f"{rasterizer.name} SVG to PNG conversion failed; browser fallback will be attempted.",
            )
        return None if _nonempty_file_exists(png_path) else Diagnostic(
            severity="warning",
            code="svg_to_png_rasterizer_failed",
            message=f"{rasterizer.name} did not produce a PNG; browser fallback will be attempted.",
        )


def svg_viewport(svg_path: Path, max_dimension: int = 2400) -> tuple:
    size = svg_viewbox_size(svg_path)
    if size is None:
        return (2400, 1400)
    width, height = size
    largest = max(width, height)
    if largest > max_dimension:
        scale = max_dimension / largest
        width = max(1, math.ceil(width * scale))
        height = max(1, math.ceil(height * scale))
    return (width, height)


def _nonempty_file_exists(path: Path, attempts: int = 5, delay_seconds: float = 0.1) -> bool:
    for _ in range(attempts):
        if path.exists() and path.stat().st_size > 0:
            return True
        time.sleep(delay_seconds)
    return False


def svg_viewbox_size(svg_path: Path) -> Optional[tuple]:
    try:
        svg_text = svg_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = re.search(r'viewBox=["\']\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)\s*["\']', svg_text)
    if not match:
        return None
    width = math.ceil(float(match.group(1)))
    height = math.ceil(float(match.group(2)))
    if width <= 0 or height <= 0:
        return None
    return (width, height)


def find_browser_executable() -> Optional[Path]:
    for name in ("google-chrome", "google-chrome-stable", "chromium"):
        match = which(name)
        if match:
            return Path(match)
    mac_candidates = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ]
    for candidate in mac_candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def find_svg_rasterizer() -> Optional[Path]:
    for name in ("resvg", "rsvg-convert"):
        match = which(name)
        if match:
            return Path(match)
    return None


def find_d2_executable(start: Optional[Path] = None) -> Optional[Path]:
    path_match = which("d2")
    if path_match:
        return Path(path_match)

    start_path = Path(start or Path.cwd()).resolve()
    candidates = [start_path / ".tools" / "d2" / "d2"]
    candidates.extend(parent / ".tools" / "d2" / "d2" for parent in start_path.parents)

    package_root = Path(__file__).resolve().parents[2]
    candidates.append(package_root / ".tools" / "d2" / "d2")

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def render_environment(executable: Path) -> dict:
    env = os.environ.copy()
    d2_home = _local_d2_home(executable)
    if d2_home is not None and env.get("ARCHWAY_D2_USE_LOCAL_PLAYWRIGHT") == "1":
        env.setdefault("PLAYWRIGHT_DRIVER_PATH", str(d2_home / "playwright-driver"))
        env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(d2_home / "ms-playwright"))
        env.setdefault("XDG_CACHE_HOME", str(d2_home / "cache"))
    return env


def _local_d2_home(executable: Path) -> Optional[Path]:
    resolved = executable.resolve()
    if resolved.name == "d2" and resolved.parent.name == "d2" and resolved.parent.parent.name == ".tools":
        return resolved.parent

    cwd_tool = Path.cwd().resolve() / ".tools" / "d2"
    if cwd_tool.exists():
        return cwd_tool
    return None
