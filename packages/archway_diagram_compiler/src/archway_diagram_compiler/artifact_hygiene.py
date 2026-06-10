"""User-visible artifact canonicalization helpers."""

from __future__ import annotations

import re
import shutil
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Sequence

from archway_diagram_compiler.models import DiagramBundle, Diagnostic, UserVisibleArtifact


USER_VISIBLE_FORMATS = {"d2", "svg", "png"}
MACHINE_ARTIFACT_SUFFIXES = {
    "flow_ledger": ".json",
    "layout_model": ".json",
    "placement_explanations": ".md",
    "qa_report": ".json",
    "render_plan": ".json",
}


def canonical_artifact_name(scenario_id: str, view_id: str, output_format: str) -> str:
    return f"{scenario_id}__{view_id}.{output_format}"


def copy_bundle_artifacts_flat(
    bundle: DiagramBundle,
    scenario_id: str,
    destination: Path,
    *,
    include_machine_artifacts: bool = True,
    clean_scenario: bool = True,
) -> list[Diagnostic]:
    """Copy one bundle into a flat, canonical user-inspection directory.

    The destination receives exactly one user-visible file per view/format with
    the canonical name ``<scenario>__<view_id>.<format>``. Existing aliases for
    the same scenario are removed before and after copy so stale Finder or
    previous-run files cannot be mistaken for compiler output.
    """

    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if clean_scenario:
        _remove_scenario_files(destination, scenario_id)

    diagnostics: list[Diagnostic] = []
    for artifact in bundle.user_visible_artifacts:
        if artifact.format not in USER_VISIBLE_FORMATS:
            continue
        target = destination / canonical_artifact_name(scenario_id, artifact.view_id, artifact.format)
        shutil.copy2(artifact.path, target)

    if include_machine_artifacts:
        for key, suffix in MACHINE_ARTIFACT_SUFFIXES.items():
            path = bundle.artifact_paths.get(key)
            if path and path.exists():
                shutil.copy2(path, destination / f"{scenario_id}__{key}{suffix}")

    diagnostics.extend(validate_flat_artifact_dir(destination, scenario_ids={scenario_id}))
    return diagnostics


def validate_flat_artifact_dir(destination: Path, *, scenario_ids: Iterable[str] | None = None) -> list[Diagnostic]:
    destination = Path(destination)
    allowed_scenarios = set(scenario_ids or [])
    diagnostics: list[Diagnostic] = []
    grouped: dict[tuple[str, str, str], list[Path]] = defaultdict(list)

    for path in destination.iterdir() if destination.exists() else []:
        if not path.is_file():
            continue
        parsed = parse_flat_artifact_name(path.name)
        if parsed is None:
            continue
        scenario_id, view_id, output_format = parsed
        if allowed_scenarios and scenario_id not in allowed_scenarios:
            continue
        grouped[(scenario_id, view_id, output_format)].append(path)

    for (scenario_id, view_id, output_format), paths in sorted(grouped.items()):
        canonical = destination / canonical_artifact_name(scenario_id, view_id, output_format)
        if len(paths) == 1 and paths[0] == canonical:
            continue
        hashes = {sha256(path.read_bytes()).hexdigest(): path for path in paths}
        if len(hashes) > 1:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="conflicting_artifact_error",
                    message=(
                        f"Conflicting artifacts found for {scenario_id}/{view_id}.{output_format}: "
                        + ", ".join(path.name for path in sorted(paths))
                    ),
                )
            )
            continue
        diagnostics.append(
            Diagnostic(
                severity="warning",
                code="duplicate_artifact_alias",
                message=(
                    f"Duplicate artifact aliases found for {scenario_id}/{view_id}.{output_format}: "
                    + ", ".join(path.name for path in sorted(paths) if path != canonical)
                ),
            )
        )
    return diagnostics


def remove_flat_artifact_aliases(destination: Path, *, scenario_ids: Iterable[str] | None = None) -> None:
    destination = Path(destination)
    allowed_scenarios = set(scenario_ids or [])
    for path in list(destination.iterdir()) if destination.exists() else []:
        if not path.is_file():
            continue
        parsed = parse_flat_artifact_name(path.name)
        if parsed is None:
            continue
        scenario_id, view_id, output_format = parsed
        if allowed_scenarios and scenario_id not in allowed_scenarios:
            continue
        canonical = destination / canonical_artifact_name(scenario_id, view_id, output_format)
        if path != canonical:
            path.unlink()


def parse_flat_artifact_name(name: str) -> tuple[str, str, str] | None:
    """Parse canonical and common duplicate alias flat artifact names."""

    match = re.match(r"^(?P<scenario>.+?)__(?P<view>.+?)(?:\s+\d+|\(\d+\))?\.(?P<format>d2|svg|png)$", name)
    if not match:
        match = re.match(
            r"^(?P<scenario>.+?)__(?P<view>.+?)(?:__|_)(?P<format>d2|svg|png)(?:\s+\d+|\(\d+\))?\.(?P=format)$",
            name,
        )
    if not match:
        return None
    view_id = match.group("view")
    for output_format in USER_VISIBLE_FORMATS:
        for suffix in (f"__{output_format}", f"_{output_format}"):
            if view_id.endswith(suffix):
                view_id = view_id[: -len(suffix)]
    return match.group("scenario"), view_id, match.group("format")


def _remove_scenario_files(destination: Path, scenario_id: str) -> None:
    for path in list(destination.glob(f"{scenario_id}__*")):
        if path.is_file():
            path.unlink()

