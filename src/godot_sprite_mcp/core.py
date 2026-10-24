"""Core image-analysis and Godot resource-generation routines.

This module deliberately has no MCP dependency so every operation can also be
used from ordinary Python code or from the command line.

Coordinate conventions
----------------------
* Image pixels are addressed with a top-left origin, x to the right and y down.
* ``inspect_spritesheet`` frames are tight bounds expressed in image pixels.
* ``extract_collision_polygon`` works on pixel *edges*: an opaque pixel at
  ``(x, y)`` occupies the square ``[x, x + 1] x [y, y + 1]``.  Polygon points
  are therefore valid around the full image/region bounds (for example
  ``0..width``) rather than only around pixel centres.
* With ``centered=True`` the points are shifted by ``width / 2`` and
  ``height / 2`` so they can be attached directly to a ``Sprite2D`` whose
  default ``centered`` property is enabled.
"""

from __future__ import annotations

import math
import os
import re
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from PIL import Image, UnidentifiedImageError

__all__ = [
    "inspect_spritesheet",
    "build_sprite_frames",
    "extract_collision_polygon",
    "build_body_collider",
    "build_character_scene",
]

# The alpha comparison is deliberately strict (alpha > threshold).
_DEFAULT_ALPHA_THRESHOLD = 10
_COLLISION_ALPHA_THRESHOLD = 10
_MAX_COLLISION_VERTICES = 24


# ---------------------------------------------------------------------------
# Shared image helpers
# ---------------------------------------------------------------------------


def _resolve_image_path(
    image_path: str | os.PathLike[str],
    project_root: str | os.PathLike[str] | None = None,
) -> Path:
    """Resolve *image_path*, supporting ``res://`` URIs and optional *project_root*."""

    raw = str(image_path)
    if raw.startswith("res://"):
        rel = raw[len("res://") :]
        if project_root is not None:
            return (Path(project_root).expanduser().resolve() / rel).resolve()
        cwd = Path.cwd().resolve()
        for parent in (cwd, *cwd.parents):
            if (parent / "project.godot").is_file() and (parent / rel).exists():
                return (parent / rel).resolve()
        return (cwd / rel).resolve()

    path = Path(image_path).expanduser()
    if not path.is_absolute() and project_root is not None:
        candidate = Path(project_root).expanduser().resolve() / path
        if candidate.exists():
            return candidate.resolve()
    return path


def _load_rgba(
    image_path: str | os.PathLike[str],
    project_root: str | os.PathLike[str] | None = None,
) -> np.ndarray:
    """Load *image_path* as an ``(H, W, 4)`` uint8 RGBA array."""

    path = _resolve_image_path(image_path, project_root)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")
    if not path.is_file():
        raise ValueError(f"image_path is not a file: {path}")

    try:
        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            # Copy because the numpy view must outlive the PIL image object.
            return np.asarray(rgba, dtype=np.uint8).copy()
    except UnidentifiedImageError as exc:
        raise ValueError(f"Unsupported or corrupt image: {path}") from exc


def _validate_alpha_threshold(alpha_threshold: int) -> int:
    if isinstance(alpha_threshold, bool) or not isinstance(
        alpha_threshold, (int, np.integer)
    ):
        raise TypeError("alpha_threshold must be an integer between 0 and 255")
    value = int(alpha_threshold)
    if not 0 <= value <= 255:
        raise ValueError("alpha_threshold must be between 0 and 255")
    return value


def _alpha_mask(
    rgba: np.ndarray, alpha_threshold: int = _DEFAULT_ALPHA_THRESHOLD
) -> np.ndarray:
    """Return a boolean mask with ``True`` for sufficiently opaque pixels."""

    return rgba[:, :, 3] > int(alpha_threshold)


def _runs(projection: np.ndarray) -> list[tuple[int, int]]:
    """Return half-open ``(start, end)`` runs of truth values in a 1-D array."""

    values = np.asarray(projection, dtype=bool).reshape(-1)
    if values.size == 0:
        return []

    padded = np.concatenate(([False], values, [False]))
    transitions = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(transitions == 1)
    ends = np.flatnonzero(transitions == -1)
    return [(int(start), int(end)) for start, end in zip(starts, ends)]


# ---------------------------------------------------------------------------
# Connected components (8-connectivity)
# ---------------------------------------------------------------------------


class _RunUnionFind:
    """Union-find over horizontal runs, used for fast 8-connected labelling."""

    def __init__(self) -> None:
        self.parent: list[int] = []
        self.rank: list[int] = []

    def add(self) -> int:
        index = len(self.parent)
        self.parent.append(index)
        self.rank.append(0)
        return index

    def find(self, item: int) -> int:
        parent = self.parent
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1


def _component_bounding_boxes(
    mask: np.ndarray,
) -> list[tuple[int, int, int, int, int]]:
    """Find 8-connected opaque components.

    Returns ``(x, y, width, height, pixel_count)`` tuples.  Pixel runs are
    unioned between adjacent rows, which is substantially faster than a
    per-pixel Python BFS while still implementing connected-component
    labelling.
    """

    height, width = mask.shape
    if height == 0 or width == 0:
        return []

    union_find = _RunUnionFind()
    run_records: list[tuple[int, int, int, int]] = []
    previous_runs: list[tuple[int, int, int]] = []

    for y in range(height):
        current_runs: list[tuple[int, int, int]] = []
        rows = _runs(mask[y])
        previous_index = 0
        for x0, x1 in rows:
            run_index = union_find.add()
            run_records.append((run_index, x0, x1, y))
            current_runs.append((x0, x1, run_index))

            # Runs are sorted.  Skip previous runs that end before this run
            # starts.  Touching endpoints count as diagonal adjacency.
            while (
                previous_index < len(previous_runs)
                and previous_runs[previous_index][1] < x0
            ):
                previous_index += 1

            probe = previous_index
            while (
                probe < len(previous_runs)
                and previous_runs[probe][0] <= x1
            ):
                union_find.union(run_index, previous_runs[probe][2])
                probe += 1

        previous_runs = current_runs

    components: dict[int, list[int]] = {}
    for run_index, x0, x1, y in run_records:
        root = union_find.find(run_index)
        record = components.get(root)
        if record is None:
            components[root] = [x0, y, x1, y + 1, x1 - x0]
        else:
            record[0] = min(record[0], x0)
            record[1] = min(record[1], y)
            record[2] = max(record[2], x1)
            record[3] = max(record[3], y + 1)
            record[4] += x1 - x0

    boxes: list[tuple[int, int, int, int, int]] = []
    for x0, y0, x1, y1, count in components.values():
        boxes.append((x0, y0, x1 - x0, y1 - y0, count))
    return boxes


# ---------------------------------------------------------------------------
# Sprite-sheet inspection
# ---------------------------------------------------------------------------


class _GridDetectionError(ValueError):
    """Internal signal that a regular grid could not be established."""


def _frame(x: int, y: int, width: int, height: int) -> dict[str, Any]:
    return {
        "x": int(x),
        "y": int(y),
        "w": int(width),
        "h": int(height),
        "pivot_bottom_center": [float(x) + width / 2.0, float(y + height)],
    }


def _detect_grid_frames(mask: np.ndarray) -> list[dict[str, Any]]:
    """Detect cells using fully transparent horizontal/vertical separators."""

    horizontal_bands = _runs(mask.any(axis=0))
    vertical_bands = _runs(mask.any(axis=1))
    if not horizontal_bands or not vertical_bands:
        raise _GridDetectionError("No opaque pixels found in the spritesheet")

    column_widths = {end - start for start, end in horizontal_bands}
    row_heights = {end - start for start, end in vertical_bands}
    if len(column_widths) != 1 or len(row_heights) != 1:
        raise _GridDetectionError(
            "Projection bands have inconsistent cell dimensions"
        )

    frames: list[dict[str, Any]] = []
    for y0, y1 in vertical_bands:
        for x0, x1 in horizontal_bands:
            # Empty Cartesian-product cells can occur in incomplete sheets.
            if not mask[y0:y1, x0:x1].any():
                continue
            frames.append(_frame(x0, y0, x1 - x0, y1 - y0))

    if not frames:
        raise _GridDetectionError("No occupied grid cells were found")
    return frames


def _cluster_frames_into_rows(
    frames: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Sort sprite bounds top-to-bottom, row-clustered, then left-to-right."""

    items = sorted(
        frames,
        key=lambda item: (
            item["y"] + item["h"] / 2.0,
            item["x"],
            item["y"],
        ),
    )
    if not items:
        return []

    median_height = float(np.median([item["h"] for item in items]))
    rows: list[dict[str, Any]] = []

    for item in items:
        item_top = float(item["y"])
        item_bottom = float(item["y"] + item["h"])
        item_center = (item_top + item_bottom) / 2.0

        best_row: dict[str, Any] | None = None
        best_overlap = -1.0
        for row in rows:
            overlap = min(item_bottom, row["bottom"]) - max(
                item_top, row["top"]
            )
            if overlap <= 0.0:
                continue

            # Prefer the row with the strongest vertical overlap.  Requiring
            # a meaningful overlap avoids gluing a tall sprite to a distant
            # row merely because its bounding box spans both.
            overlap_ratio = overlap / max(
                1.0, min(float(item["h"]), row["bottom"] - row["top"])
            )
            centre_tolerance = 0.35 * max(
                1.0, min(median_height, float(item["h"]))
            )
            centre_close = abs(item_center - row["center"]) <= centre_tolerance
            if overlap_ratio >= 0.2 or centre_close:
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_row = row

        if best_row is None:
            rows.append(
                {
                    "items": [item],
                    "top": item_top,
                    "bottom": item_bottom,
                    "center": item_center,
                }
            )
        else:
            best_row["items"].append(item)
            best_row["top"] = min(best_row["top"], item_top)
            best_row["bottom"] = max(best_row["bottom"], item_bottom)
            best_row["center"] = (
                best_row["top"] + best_row["bottom"]
            ) / 2.0

    rows.sort(key=lambda row: (row["center"], row["top"]))
    ordered: list[dict[str, Any]] = []
    for row in rows:
        row["items"].sort(key=lambda item: (item["x"], item["y"], item["w"]))
        ordered.extend(row["items"])
    return ordered


def _detect_island_frames(mask: np.ndarray) -> list[dict[str, Any]]:
    boxes = _component_bounding_boxes(mask)
    frames = [_frame(x, y, width, height) for x, y, width, height, _ in boxes]
    return _cluster_frames_into_rows(frames)


def inspect_spritesheet(
    image_path: str,
    alpha_threshold: int = 10,
    mode: str = "auto",
    project_root: str | None = None,
) -> dict[str, Any]:
    """Inspect a spritesheet and return frame rectangles.

    Parameters
    ----------
    image_path:
        Path to a PNG (or ``res://...`` URI when *project_root* is given or
        inferable from the working directory).
    alpha_threshold:
        Alpha values strictly greater than this are considered opaque.
    mode:
        ``"grid"`` uses transparent separator projections, ``"islands"`` uses
        tight connected-component bounds, and ``"auto"`` tries a regular grid
        first, falling back to islands when the grid is inconsistent.
    project_root:
        Optional Godot project root directory for resolving ``res://`` URIs.

    Returns
    -------
    dict
        ``image_width``, ``image_height``, the detected ``mode``,
        ``frame_count`` and a top-to-bottom/left-to-right list of frames.
    """

    threshold = _validate_alpha_threshold(alpha_threshold)
    if not isinstance(mode, str):
        raise TypeError("mode must be one of 'auto', 'grid' or 'islands'")
    requested_mode = mode.strip().lower()
    if requested_mode not in {"auto", "grid", "islands"}:
        raise ValueError("mode must be one of 'auto', 'grid' or 'islands'")

    rgba = _load_rgba(image_path, project_root=project_root)
    height, width = rgba.shape[:2]
    mask = _alpha_mask(rgba, threshold)

    if not mask.any():
        raise ValueError(
            "No pixels with alpha greater than alpha_threshold were found"
        )

    detected_mode: str
    if requested_mode == "islands":
        frames = _detect_island_frames(mask)
        detected_mode = "islands"
    else:
        try:
            frames = _detect_grid_frames(mask)
            detected_mode = "grid"
        except _GridDetectionError:
            if requested_mode == "grid":
                raise ValueError(
                    "Could not detect a regular grid. Use mode='islands' or "
                    "mode='auto' for irregular spritesheets."
                ) from None
            frames = _detect_island_frames(mask)
            detected_mode = "islands"

    # Re-number after final ordering so ids always follow reading order.
    for index, frame in enumerate(frames):
        frame["id"] = index

    # Keep a predictable public key order.
    ordered_frames = [
        {
            "id": frame["id"],
            "x": frame["x"],
            "y": frame["y"],
            "w": frame["w"],
            "h": frame["h"],
            "pivot_bottom_center": frame["pivot_bottom_center"],
        }
        for frame in frames
    ]

    return {
        "image_width": int(width),
        "image_height": int(height),
        "mode": detected_mode,
        "frame_count": len(ordered_frames),
        "frames": ordered_frames,
    }


# ---------------------------------------------------------------------------
# Godot SpriteFrames (.tres) generation
# ---------------------------------------------------------------------------


def _resolve_within_project(
    project_root: Path,
    candidate: Path,
    *,
    label: str,
) -> tuple[Path, Path]:
    """Resolve *candidate* and ensure it lives below *project_root*."""

    resolved = candidate.expanduser().resolve()
    try:
        relative = resolved.relative_to(project_root)
    except ValueError as exc:
        raise ValueError(
            f"{label} must be inside project_root ({project_root}); "
            f"got {resolved}"
        ) from exc
    return resolved, relative


def _project_paths(
    project_root: str,
    image_path: str,
    output_tres: str,
) -> tuple[Path, Path, str]:
    """Resolve project, image and output paths and produce the ``res://`` URI."""

    root = Path(project_root).expanduser()
    if not root.exists():
        raise FileNotFoundError(f"project_root does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"project_root is not a directory: {root}")
    root = root.resolve()

    raw_image = str(image_path)
    if raw_image.startswith("res://"):
        image_candidate = root / raw_image[len("res://") :]
    else:
        supplied_image = Path(raw_image).expanduser()
        if supplied_image.is_absolute():
            image_candidate = supplied_image
        else:
            project_relative = root / supplied_image
            if project_relative.exists():
                image_candidate = project_relative
            else:
                image_candidate = Path.cwd() / supplied_image

    resolved_image, image_relative = _resolve_within_project(
        root, image_candidate, label="image_path"
    )
    if not resolved_image.is_file():
        raise FileNotFoundError(f"Image not found: {resolved_image}")

    raw_output = str(output_tres)
    if raw_output.startswith("res://"):
        output_candidate = root / raw_output[len("res://") :]
    else:
        supplied_output = Path(raw_output).expanduser()
        output_candidate = (
            supplied_output
            if supplied_output.is_absolute()
            else root / supplied_output
        )

    # The output may live outside the project if the caller explicitly asks
    # for an absolute path, but everything Godot references must be inside it.
    resolved_output = output_candidate.resolve()
    resource_uri = "res://" + image_relative.as_posix()
    return resolved_image, resolved_output, resource_uri


def _require_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _require_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field} must be an integer")
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise TypeError(f"{field} must be an integer")


def _gd_string(value: str) -> str:
    """Return a Godot 4 StringName literal (``&"..."``)."""

    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'&"{escaped}"'


def _format_float(value: float) -> str:
    """Format a number consistently for Godot text resources."""

    number = float(value)
    if abs(number) < 1e-12:
        number = 0.0
    if number.is_integer():
        return f"{number:.1f}"
    return f"{number:.6f}".rstrip("0").rstrip(".")


def _safe_subresource_name(name: str, fallback_index: int) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_")
    if not cleaned:
        cleaned = f"animation_{fallback_index}"
    if cleaned[0].isdigit():
        cleaned = f"animation_{cleaned}"
    return cleaned


def _normalise_animations(
    animations: Sequence[dict[str, Any]],
    image_width: int,
    image_height: int,
) -> tuple[list[dict[str, Any]], int]:
    """Validate animation input and count AtlasTexture subresources."""

    if not isinstance(animations, (list, tuple)):
        raise TypeError("animations must be a list of animation dictionaries")
    if not animations:
        raise ValueError("animations must contain at least one animation")

    normalised: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    frame_total = 0

    for animation_index, raw_animation in enumerate(animations):
        if not isinstance(raw_animation, dict):
            raise TypeError(f"animations[{animation_index}] must be a dictionary")

        name = raw_animation.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"animations[{animation_index}].name must be a non-empty string")
        name = name.strip()
        if name in seen_names:
            raise ValueError(f"Duplicate animation name: {name!r}")
        seen_names.add(name)

        raw_frames = raw_animation.get("frames")
        if not isinstance(raw_frames, (list, tuple)):
            raise TypeError(f"animations[{animation_index}].frames must be a list")

        fps = _require_number(
            raw_animation.get("fps", 10.0),
            f"animations[{animation_index}].fps",
        )
        if fps < 0:
            raise ValueError(f"animations[{animation_index}].fps must be >= 0")

        loop = raw_animation.get("loop", True)
        if not isinstance(loop, bool):
            raise TypeError(f"animations[{animation_index}].loop must be a boolean")

        normalised_frames: list[dict[str, Any]] = []
        for frame_index, raw_frame in enumerate(raw_frames):
            prefix = f"animations[{animation_index}].frames[{frame_index}]"
            if not isinstance(raw_frame, dict):
                raise TypeError(f"{prefix} must be a dictionary")

            x = _require_int(raw_frame.get("x"), f"{prefix}.x")
            y = _require_int(raw_frame.get("y"), f"{prefix}.y")
            width = _require_int(raw_frame.get("w"), f"{prefix}.w")
            height = _require_int(raw_frame.get("h"), f"{prefix}.h")

            if width <= 0 or height <= 0:
                raise ValueError(f"{prefix}.w and {prefix}.h must be positive")
            if x < 0 or y < 0:
                raise ValueError(f"{prefix}.x and {prefix}.y must be >= 0")
            if x + width > image_width or y + height > image_height:
                raise ValueError(
                    f"{prefix} region Rect2({x}, {y}, {width}, {height}) "
                    f"exceeds the {image_width}x{image_height} image"
                )

            duration = _require_number(
                raw_frame.get("duration", 1.0), f"{prefix}.duration"
            )
            if duration <= 0:
                raise ValueError(f"{prefix}.duration must be > 0")

            normalised_frames.append(
                {
                    "x": x,
                    "y": y,
                    "w": width,
                    "h": height,
                    "duration": duration,
                }
            )

        frame_total += len(normalised_frames)
        normalised.append(
            {
                "name": name,
                "fps": fps,
                "loop": loop,
                "frames": normalised_frames,
            }
        )

    return normalised, frame_total


def _render_sprite_frames_tres(
    resource_uri: str,
    animations: Sequence[dict[str, Any]],
    atlas_count: int,
) -> tuple[str, int]:
    """Render the Godot 4 ``SpriteFrames`` resource text.

    ``load_steps`` follows the project specification:
    1 ext_resource + N AtlasTexture sub_resources + 1 main resource.
    """

    load_steps = 1 + atlas_count + 1
    lines: list[str] = [
        f'[gd_resource type="SpriteFrames" load_steps={load_steps} format=3]',
        "",
        f'[ext_resource type="Texture2D" path="{resource_uri}" id="1_tex"]',
        "",
    ]

    subresource_ids: list[list[str]] = []
    used_ids: set[str] = set()
    for animation_index, animation in enumerate(animations):
        base = _safe_subresource_name(animation["name"], animation_index)
        current_ids: list[str] = []
        for frame_index, frame in enumerate(animation["frames"]):
            candidate = f"AtlasTexture_{base}_{frame_index}"
            suffix = 1
            while candidate in used_ids:
                candidate = f"AtlasTexture_{base}_{frame_index}_{suffix}"
                suffix += 1
            used_ids.add(candidate)
            current_ids.append(candidate)

            lines.extend(
                [
                    f'[sub_resource type="AtlasTexture" id="{candidate}"]',
                    'atlas = ExtResource("1_tex")',
                    f'region = Rect2({frame["x"]}, {frame["y"]}, '
                    f'{frame["w"]}, {frame["h"]})',
                    "",
                ]
            )
        subresource_ids.append(current_ids)

    lines.append("[resource]")

    animation_blocks: list[str] = []
    for animation, ids in zip(animations, subresource_ids):
        frame_blocks: list[str] = []
        for frame, subresource_id in zip(animation["frames"], ids):
            frame_blocks.append(
                "{\n"
                f'"duration": {_format_float(frame["duration"])},\n'
                f'"texture": SubResource("{subresource_id}")\n'
                "}"
            )

        if frame_blocks:
            frames_text = "[" + ", ".join(frame_blocks) + "]"
        else:
            frames_text = "[]"

        animation_blocks.append(
            "{\n"
            f'"frames": {frames_text},\n'
            f'"loop": {str(animation["loop"]).lower()},\n'
            f'"name": {_gd_string(animation["name"])},\n'
            f'"speed": {_format_float(animation["fps"])}\n'
            "}"
        )

    lines.append("animations = [" + ", ".join(animation_blocks) + "]")
    return "\n".join(lines) + "\n", load_steps


def build_sprite_frames(
    project_root: str,
    image_path: str,
    animations: list[dict],
    output_tres: str,
) -> dict[str, Any]:
    """Generate a Godot 4.x SpriteFrames ``.tres`` resource.

    ``image_path`` must be inside ``project_root`` so it can be referenced as a
    ``res://`` URI.  Each animation may define ``name``, ``fps``, ``loop`` and a
    list of ``{x, y, w, h}`` texture regions.  Frames default to a duration of
    ``1.0``; the animation speed controls playback rate.

    Returns metadata about the written resource, including its path,
    ``load_steps`` and frame count.
    """

    resolved_image, output_path, resource_uri = _project_paths(
        project_root, image_path, output_tres
    )

    rgba = _load_rgba(resolved_image)
    image_height, image_width = rgba.shape[:2]
    normalised, frame_total = _normalise_animations(
        animations, image_width, image_height
    )

    text, load_steps = _render_sprite_frames_tres(
        resource_uri, normalised, frame_total
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=str(output_path.parent),
        text=True,
    )
    try:
        with os.fdopen(
            file_descriptor, "w", encoding="utf-8", newline="\n"
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, output_path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise

    return {
        "output_tres": str(output_path),
        "texture_path": resource_uri,
        "load_steps": int(load_steps),
        "animation_count": len(normalised),
        "frame_count": int(frame_total),
    }


# ---------------------------------------------------------------------------
# Collision polygon extraction
# ---------------------------------------------------------------------------
#
# Boundary tracing works on the pixel-edge graph.  Every opaque pixel emits an
# oriented edge for each side that touches transparency; the resulting loops
# are exact pixel rectangles (0..width, 0..height) rather than half-pixel
# centre approximations.  At a diagonal junction the clockwise-most outgoing
# edge is selected, which is the standard Moore-neighbour boundary-walk rule
# and prevents two diagonally touching lobes from being stitched into a
# self-touching figure-eight.


def _boundary_loops(mask: np.ndarray) -> list[np.ndarray]:
    """Trace every oriented outer/hole boundary in a tight boolean mask.

    Foreground is kept on the right of each directed edge, so outer contours
    are clockwise in screen coordinates and hole contours are anticlockwise.
    """

    height, width = mask.shape
    if height == 0 or width == 0 or not mask.any():
        return []

    above = np.zeros_like(mask)
    above[1:, :] = mask[:-1, :]
    below = np.zeros_like(mask)
    below[:-1, :] = mask[1:, :]
    left = np.zeros_like(mask)
    left[:, 1:] = mask[:, :-1]
    right = np.zeros_like(mask)
    right[:, :-1] = mask[:, 1:]

    starts: list[tuple[int, int]] = []
    ends: list[tuple[int, int]] = []

    top_y, top_x = np.nonzero(mask & ~above)
    starts.extend(zip(top_x.tolist(), top_y.tolist()))
    ends.extend(zip((top_x + 1).tolist(), top_y.tolist()))

    right_y, right_x = np.nonzero(mask & ~right)
    starts.extend(zip((right_x + 1).tolist(), right_y.tolist()))
    ends.extend(zip((right_x + 1).tolist(), (right_y + 1).tolist()))

    bottom_y, bottom_x = np.nonzero(mask & ~below)
    starts.extend(zip((bottom_x + 1).tolist(), (bottom_y + 1).tolist()))
    ends.extend(zip(bottom_x.tolist(), (bottom_y + 1).tolist()))

    left_y, left_x = np.nonzero(mask & ~left)
    starts.extend(zip(left_x.tolist(), (left_y + 1).tolist()))
    ends.extend(zip(left_x.tolist(), left_y.tolist()))

    edge_count = len(starts)
    if edge_count == 0:
        return []

    outgoing: dict[
        tuple[int, int], list[tuple[tuple[int, int], int]]
    ] = defaultdict(list)
    for edge_index, (start, end) in enumerate(zip(starts, ends)):
        outgoing[start].append((end, edge_index))

    visited = bytearray(edge_count)
    loops: list[np.ndarray] = []

    for first_edge in range(edge_count):
        if visited[first_edge]:
            continue
        visited[first_edge] = 1

        start = starts[first_edge]
        previous = start
        current = ends[first_edge]
        path: list[tuple[int, int]] = [start]

        while current != start:
            path.append(current)
            candidates = [
                (neighbour, candidate_index)
                for neighbour, candidate_index in outgoing.get(current, ())
                if not visited[candidate_index]
            ]
            if not candidates:
                path = []
                break

            incoming_x = current[0] - previous[0]
            incoming_y = current[1] - previous[1]

            def clockwise_turn(
                candidate: tuple[tuple[int, int], int]
            ) -> float:
                neighbour, _ = candidate
                outgoing_x = neighbour[0] - current[0]
                outgoing_y = neighbour[1] - current[1]
                cross = incoming_x * outgoing_y - incoming_y * outgoing_x
                dot = incoming_x * outgoing_x + incoming_y * outgoing_y
                return math.atan2(cross, dot)

            next_point, next_edge = max(candidates, key=clockwise_turn)
            visited[next_edge] = 1
            previous = current
            current = next_point

        # The start is not appended; the closing edge is implicit.
        if current == start and len(path) >= 4:
            loops.append(np.asarray(path, dtype=np.float64))

    return loops


def _polygon_area(points: np.ndarray) -> float:
    if len(points) < 3:
        return 0.0
    x = points[:, 0]
    y = points[:, 1]
    return float(
        0.5
        * (
            np.dot(x, np.roll(y, -1))
            - np.dot(y, np.roll(x, -1))
        )
    )


def _largest_outer_contour(mask: np.ndarray) -> np.ndarray:
    """Extract the largest outer boundary in local pixel-edge coordinates."""

    loops = _boundary_loops(mask)
    if not loops:
        raise ValueError("Could not trace an outer contour")

    best_area = -1.0
    best_points: np.ndarray | None = None
    for loop in loops:
        area = abs(_polygon_area(loop))
        if area > best_area:
            best_area = area
            best_points = loop

    if best_points is None or len(best_points) < 3 or best_area <= 0.0:
        raise ValueError("The opaque region did not produce a usable contour")
    return best_points


def _point_to_segment_distance(
    points: np.ndarray,
    start: np.ndarray,
    end: np.ndarray,
) -> np.ndarray:
    """Vectorised point-to-segment distance used by RDP."""

    segment = end - start
    length_squared = float(np.dot(segment, segment))
    if length_squared <= 1e-20:
        return np.linalg.norm(points - start, axis=1)

    projection = np.dot(points - start, segment) / length_squared
    projection = np.clip(projection, 0.0, 1.0)
    closest = start + projection[:, None] * segment
    return np.linalg.norm(points - closest, axis=1)


def _rdp_open(points: np.ndarray, epsilon: float) -> np.ndarray:
    """Ramer-Douglas-Peucker simplification of an open polyline."""

    count = len(points)
    if count <= 2:
        return points.copy()

    keep = np.zeros(count, dtype=bool)
    keep[0] = True
    keep[-1] = True
    stack: list[tuple[int, int]] = [(0, count - 1)]

    while stack:
        start_index, end_index = stack.pop()
        if end_index <= start_index + 1:
            continue
        start = points[start_index]
        end = points[end_index]
        distances = _point_to_segment_distance(
            points[start_index + 1 : end_index], start, end
        )
        if distances.size == 0:
            continue
        relative_index = int(np.argmax(distances))
        maximum = float(distances[relative_index])
        if maximum > epsilon:
            split_index = start_index + 1 + relative_index
            keep[split_index] = True
            stack.append((start_index, split_index))
            stack.append((split_index, end_index))

    return points[keep]


def _deduplicate_closed_points(points: np.ndarray) -> np.ndarray:
    if len(points) == 0:
        return points
    cleaned = [points[0]]
    for point in points[1:]:
        if not np.allclose(point, cleaned[-1], rtol=0.0, atol=1e-9):
            cleaned.append(point)
    if len(cleaned) > 1 and np.allclose(
        cleaned[0], cleaned[-1], rtol=0.0, atol=1e-9
    ):
        cleaned.pop()
    return np.asarray(cleaned, dtype=np.float64)


def _rdp_closed(points: np.ndarray, epsilon: float) -> np.ndarray:
    """Simplification of a closed polygon without duplicating the first point."""

    points = _deduplicate_closed_points(np.asarray(points, dtype=np.float64))
    if len(points) <= 3:
        return points

    first = points[0]
    distances = np.linalg.norm(points - first, axis=1)
    split_index = int(np.argmax(distances))
    if split_index <= 0 or split_index >= len(points) - 1:
        split_index = len(points) // 2

    first_half = _rdp_open(points[: split_index + 1], epsilon)
    second_half = _rdp_open(
        np.vstack((points[split_index:], points[:1])), epsilon
    )
    simplified = np.vstack((first_half[:-1], second_half[:-1]))
    return _deduplicate_closed_points(simplified)


def _cross(origin: np.ndarray, first: np.ndarray, second: np.ndarray) -> float:
    return float(
        (first[0] - origin[0]) * (second[1] - origin[1])
        - (first[1] - origin[1]) * (second[0] - origin[0])
    )


def _on_segment(
    start: np.ndarray, point: np.ndarray, end: np.ndarray, tolerance: float
) -> bool:
    return (
        min(start[0], end[0]) - tolerance
        <= point[0]
        <= max(start[0], end[0]) + tolerance
        and min(start[1], end[1]) - tolerance
        <= point[1]
        <= max(start[1], end[1]) + tolerance
    )


def _segments_intersect(
    first_start: np.ndarray,
    first_end: np.ndarray,
    second_start: np.ndarray,
    second_end: np.ndarray,
    tolerance: float = 1e-9,
) -> bool:
    o1 = _cross(first_start, first_end, second_start)
    o2 = _cross(first_start, first_end, second_end)
    o3 = _cross(second_start, second_end, first_start)
    o4 = _cross(second_start, second_end, first_end)

    if ((o1 > tolerance and o2 < -tolerance) or (
        o1 < -tolerance and o2 > tolerance
    )) and (
        (o3 > tolerance and o4 < -tolerance)
        or (o3 < -tolerance and o4 > tolerance)
    ):
        return True

    if abs(o1) <= tolerance and _on_segment(
        first_start, second_start, first_end, tolerance
    ):
        return True
    if abs(o2) <= tolerance and _on_segment(
        first_start, second_end, first_end, tolerance
    ):
        return True
    if abs(o3) <= tolerance and _on_segment(
        second_start, first_start, second_end, tolerance
    ):
        return True
    if abs(o4) <= tolerance and _on_segment(
        second_start, first_end, second_end, tolerance
    ):
        return True
    return False


def _is_simple_polygon(points: np.ndarray) -> bool:
    count = len(points)
    if count < 4:
        return True
    for first_index in range(count):
        first_start = points[first_index]
        first_end = points[(first_index + 1) % count]
        for second_index in range(first_index + 1, count):
            next_second = (second_index + 1) % count
            if (
                second_index == first_index
                or next_second == first_index
                or second_index == (first_index + 1) % count
            ):
                continue
            if _segments_intersect(
                first_start,
                first_end,
                points[second_index],
                points[next_second],
            ):
                return False
    return True


def _convex_hull(points: np.ndarray) -> np.ndarray:
    """Andrew monotone-chain hull; collinear interior points are removed."""

    ordered = sorted(
        {(float(point[0]), float(point[1])) for point in points}
    )
    if len(ordered) <= 2:
        return np.asarray(ordered, dtype=np.float64)

    def build_half(sequence: list[tuple[float, float]]) -> list[tuple[float, float]]:
        half: list[tuple[float, float]] = []
        for point in sequence:
            while len(half) >= 2:
                origin = np.asarray(half[-2])
                first = np.asarray(half[-1])
                second = np.asarray(point)
                if _cross(origin, first, second) > 1e-12:
                    break
                half.pop()
            half.append(point)
        return half

    lower = build_half(ordered)
    upper = build_half(list(reversed(ordered)))
    return np.asarray(lower[:-1] + upper[:-1], dtype=np.float64)


def _bounding_box_polygon(points: np.ndarray) -> np.ndarray:
    x_min = float(np.min(points[:, 0]))
    y_min = float(np.min(points[:, 1]))
    x_max = float(np.max(points[:, 0]))
    y_max = float(np.max(points[:, 1]))
    return np.asarray(
        [
            [x_min, y_min],
            [x_max, y_min],
            [x_max, y_max],
            [x_min, y_max],
        ],
        dtype=np.float64,
    )


def _normalise_polygon(points: np.ndarray) -> np.ndarray:
    """Make winding clockwise in screen coordinates and start top-left."""

    points = _deduplicate_closed_points(points)
    if len(points) < 3:
        return points
    if _polygon_area(points) < 0:
        points = points[::-1].copy()
    start_index = min(
        range(len(points)),
        key=lambda index: (round(float(points[index, 0]), 12),
                           round(float(points[index, 1]), 12)),
    )
    return np.roll(points, -start_index, axis=0)


def _simplify_collision_polygon(points: np.ndarray, epsilon: float) -> np.ndarray:
    """RDP simplification constrained to a collision-friendly vertex count."""

    if not math.isfinite(epsilon) or epsilon < 0:
        raise ValueError("epsilon must be a finite number >= 0")

    working = points
    current_epsilon = float(epsilon)
    simplified = _rdp_closed(working, current_epsilon)

    # The public contract asks for roughly 4-24 vertices.  If a very detailed
    # contour is still too complex, progressively raise the tolerance while
    # keeping the shape's bounding box.
    attempts = 0
    while len(simplified) > _MAX_COLLISION_VERTICES and attempts < 24:
        current_epsilon = max(
            current_epsilon * 1.6,
            current_epsilon + 0.75,
            0.75,
        )
        simplified = _rdp_closed(working, current_epsilon)
        attempts += 1

    if len(simplified) > _MAX_COLLISION_VERTICES:
        simplified = _convex_hull(working)
        if len(simplified) > _MAX_COLLISION_VERTICES:
            simplified = _bounding_box_polygon(working)

    if len(simplified) < 3 or abs(_polygon_area(simplified)) <= 1e-8:
        simplified = _bounding_box_polygon(working)

    simplified = _normalise_polygon(simplified)

    if not _is_simple_polygon(simplified):
        # Convex hulls are simple by construction.  Use one as a conservative
        # fallback if a highly simplified contour ever self-intersects.
        simplified = _convex_hull(working)
        if len(simplified) > _MAX_COLLISION_VERTICES:
            hull_epsilon = max(current_epsilon, 1.0)
            for _ in range(24):
                candidate = _rdp_closed(simplified, hull_epsilon)
                if len(candidate) <= _MAX_COLLISION_VERTICES:
                    simplified = candidate
                    break
                hull_epsilon *= 1.5
        if len(simplified) < 3 or not _is_simple_polygon(simplified):
            simplified = _bounding_box_polygon(working)

    simplified = _normalise_polygon(simplified)
    if len(simplified) > _MAX_COLLISION_VERTICES:
        simplified = _bounding_box_polygon(working)
    return simplified


def _round_coordinate(value: float) -> float:
    rounded = round(float(value), 2)
    return 0.0 if rounded == 0.0 else rounded


def _format_godot_float(value: float) -> str:
    if abs(value) < 1e-9:
        value = 0.0
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    if "." not in text:
        text += ".0"
    return "0.0" if text == "-0.0" else text


def _normalise_region(
    region: dict[str, Any] | None,
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int]:
    if region is None:
        return 0, 0, image_width, image_height
    if not isinstance(region, dict):
        raise TypeError("region must be a dictionary or None")

    x = _require_int(region.get("x"), "region.x")
    y = _require_int(region.get("y"), "region.y")
    width = _require_int(region.get("w"), "region.w")
    height = _require_int(region.get("h"), "region.h")

    if width <= 0 or height <= 0:
        raise ValueError("region.w and region.h must be positive")
    if x < 0 or y < 0:
        raise ValueError("region.x and region.y must be >= 0")
    if x + width > image_width or y + height > image_height:
        raise ValueError(
            f"region Rect2({x}, {y}, {width}, {height}) exceeds the "
            f"{image_width}x{image_height} image"
        )
    return x, y, width, height


def extract_collision_polygon(
    image_path: str,
    region: dict | None = None,
    epsilon: float = 2.0,
    centered: bool = True,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Extract a simplified outer collision contour from opaque pixels.

    This optional polygon extractor is intended for static objects and
    irregular scenery. For moving characters/monsters use
    :func:`build_body_collider` to obtain a stable feet-aligned rectangle or
    capsule body collider.

    The largest external contour is traced with marching squares, simplified
    with Ramer-Douglas-Peucker, and normalised to a simple clockwise polygon of
    at most 24 vertices.  With ``centered=True`` coordinates are relative to
    the centre of the image or the supplied region, matching Godot 4's
    ``Sprite2D.centered`` default.

    Returns
    -------
    dict
        ``points``, ``vertex_count``, ``packed_vector2_array`` and a ready to
        paste ``tscn_snippet``.
    """

    rgba = _load_rgba(image_path, project_root=project_root)
    image_height, image_width = rgba.shape[:2]
    crop_x, crop_y, crop_width, crop_height = _normalise_region(
        region, image_width, image_height
    )

    crop_alpha = rgba[
        crop_y : crop_y + crop_height,
        crop_x : crop_x + crop_width,
        3,
    ]
    mask = crop_alpha > _COLLISION_ALPHA_THRESHOLD
    if not mask.any():
        raise ValueError(
            "No pixels with alpha greater than 10 were found in the requested "
            "region"
        )

    # Cropping to the foreground bounding box keeps marching squares and loop
    # tracing proportional to the sprite rather than to the whole sheet.
    foreground_y, foreground_x = np.nonzero(mask)
    local_x0 = int(foreground_x.min())
    local_y0 = int(foreground_y.min())
    local_x1 = int(foreground_x.max()) + 1
    local_y1 = int(foreground_y.max()) + 1
    tight_mask = mask[local_y0:local_y1, local_x0:local_x1]

    local_points = _largest_outer_contour(tight_mask)
    # Convert from the tight crop to coordinates relative to the requested
    # image/region.  The traced coordinates already use pixel-edge units.
    local_points[:, 0] += local_x0
    local_points[:, 1] += local_y0

    simplified = _simplify_collision_polygon(local_points, float(epsilon))

    center_x = crop_width / 2.0
    center_y = crop_height / 2.0
    if centered:
        godot_points = np.column_stack(
            (
                simplified[:, 0] - center_x,
                simplified[:, 1] - center_y,
            )
        )
    else:
        godot_points = simplified.copy()

    points: list[list[float]] = [
        [_round_coordinate(point[0]), _round_coordinate(point[1])]
        for point in godot_points
    ]

    # Rounding can create duplicate adjacent vertices at very small epsilons.
    deduplicated: list[list[float]] = []
    for point in points:
        if not deduplicated or point != deduplicated[-1]:
            deduplicated.append(point)
    if len(deduplicated) > 1 and deduplicated[0] == deduplicated[-1]:
        deduplicated.pop()
    if len(deduplicated) < 3:
        raise ValueError("Simplification produced fewer than three vertices")
    points = deduplicated

    packed = "PackedVector2Array(" + ", ".join(
        f"{_format_godot_float(point[0])}, {_format_godot_float(point[1])}"
        for point in points
    ) + ")"
    snippet = (
        '[node name="CollisionPolygon2D" type="CollisionPolygon2D" '
        'parent="."]\n'
        f"polygon = {packed}"
    )

    return {
        "points": points,
        "vertex_count": len(points),
        "packed_vector2_array": packed,
        "tscn_snippet": snippet,
    }


def _normalise_body_shape(shape: str) -> str:
    if not isinstance(shape, str):
        raise TypeError("shape must be 'rectangle' or 'capsule'")
    normalised = shape.strip().lower()
    if normalised in {"rectangle", "rect", "rectangleshape2d", "rectangle_shape_2d"}:
        return "rectangle"
    if normalised in {"capsule", "capsuleshape2d", "capsule_shape_2d"}:
        return "capsule"
    raise ValueError("shape must be 'rectangle' or 'capsule'")


def _normalise_body_frames(
    frames: Sequence[dict[str, Any]],
    image_width: int,
    image_height: int,
) -> tuple[list[tuple[int, int, int, int]], int, int]:
    """Validate a selected animation's frame regions."""

    if not isinstance(frames, (list, tuple)):
        raise TypeError("frames must be a list of frame region dictionaries")
    if not frames:
        raise ValueError("frames must contain at least one animation frame")

    regions: list[tuple[int, int, int, int]] = []
    frame_width: int | None = None
    frame_height: int | None = None

    for index, raw_frame in enumerate(frames):
        if not isinstance(raw_frame, dict):
            raise TypeError(f"frames[{index}] must be a dictionary")
        region = _normalise_region(raw_frame, image_width, image_height)
        width = region[2]
        height = region[3]
        if frame_width is None:
            frame_width = width
            frame_height = height
        elif width != frame_width or height != frame_height:
            raise ValueError(
                "All frames in one body-collision sequence must have the same "
                f"w/h; frames[0] is {frame_width}x{frame_height}, "
                f"frames[{index}] is {width}x{height}"
            )
        regions.append(region)

    assert frame_width is not None and frame_height is not None
    return regions, frame_width, frame_height


def build_body_collider(
    image_path: str,
    frames: list[dict],
    shape: str = "rectangle",
    alpha_threshold: int = 10,
    thickness_ratio: float = 0.30,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Build a stable single-shape body collider from an animation sequence.

    Unlike :func:`extract_collision_polygon`, which is intended for static
    objects, this function is designed for moving characters and monsters. It
    overlays every frame in the selected animation, measures the full character
    height, filters thin weapon/arm columns with a vertical-thickness test, and
    returns a ``RectangleShape2D`` (default) or ``CapsuleShape2D`` aligned to a
    feet-at-origin root.

    Parameters
    ----------
    image_path:
        Spritesheet image containing all frame regions (supports ``res://``).
    frames:
        All regions of one animation. Every frame must have the same ``w`` and
        ``h``. Each item is ``{"x": int, "y": int, "w": int, "h": int}``.
    shape:
        ``"rectangle"`` (default) or ``"capsule"``.
    alpha_threshold:
        Opaque cutoff; pixels with alpha strictly greater are included.
    thickness_ratio:
        Minimum fraction of the character height a column must occupy to be
        part of the core body. Defaults to 0.30.
    project_root:
        Optional Godot project root directory for resolving ``res://`` URIs.

    Returns
    -------
    dict
        Height/width measurements, feet-aligned ``sprite_offset`` and
        ``collision_position``, shape parameters, and ready-to-paste Godot 4
        sub-resource/node snippets.
    """

    threshold = _validate_alpha_threshold(alpha_threshold)
    shape_kind = _normalise_body_shape(shape)

    if not isinstance(thickness_ratio, (int, float)) or isinstance(
        thickness_ratio, bool
    ):
        raise TypeError("thickness_ratio must be a number")
    ratio = float(thickness_ratio)
    if not math.isfinite(ratio) or not 0.0 < ratio <= 1.0:
        raise ValueError("thickness_ratio must be in the range (0, 1]")

    rgba = _load_rgba(image_path, project_root=project_root)
    image_height, image_width = rgba.shape[:2]
    regions, frame_width, frame_height = _normalise_body_frames(
        frames, image_width, image_height
    )

    masks: list[np.ndarray] = []
    tops: list[int] = []
    bottoms: list[int] = []
    raw_left = frame_width
    raw_right = 0

    for x, y, width, height in regions:
        crop = rgba[y : y + height, x : x + width, 3]
        mask = crop > threshold
        if not mask.any():
            continue
        ys, xs = np.nonzero(mask)
        masks.append(mask)
        tops.append(int(ys.min()))
        bottoms.append(int(ys.max()) + 1)
        raw_left = min(raw_left, int(xs.min()))
        raw_right = max(raw_right, int(xs.max()) + 1)

    if not masks:
        raise ValueError(
            "No pixels with alpha greater than alpha_threshold were found in "
            "the selected animation frames"
        )

    top = min(tops)
    bottom = max(bottoms)
    height = bottom - top
    if height <= 0:
        raise ValueError("The selected animation frames have no usable height")

    raw_width = raw_right - raw_left
    if raw_width <= 0:
        raise ValueError("The selected animation frames have no usable width")

    # Average the aligned binary masks. Summing each column gives the average
    # number of opaque pixels in that column across the whole animation. This
    # keeps a column that is consistently present, while suppressing thin
    # weapons/arms that only occupy a few vertical pixels.
    stacked = np.stack(masks).astype(np.float32)
    mean_mask = stacked.mean(axis=0)
    column_heights = mean_mask.sum(axis=0)

    minimum_column_height = ratio * float(height)
    core_columns = np.flatnonzero(column_heights >= minimum_column_height)

    if core_columns.size:
        body_left = int(core_columns[0])
        body_right = int(core_columns[-1]) + 1
    else:
        # Extremely sparse sequences: fall back to the complete raw extent.
        body_left = raw_left
        body_right = raw_right

    target_width = min(float(raw_width), max(1.0, minimum_column_height))
    body_width = body_right - body_left

    # Preserve a usable minimum body width while never exceeding the raw
    # non-transparent extent. Expansion is centered on the detected core.
    if body_width < target_width:
        desired = min(raw_width, max(1, int(math.ceil(target_width))))
        center = (body_left + body_right) / 2.0
        expanded_left = int(round(center - desired / 2.0))
        expanded_right = expanded_left + desired

        if expanded_left < raw_left:
            shift = raw_left - expanded_left
            expanded_left += shift
            expanded_right += shift
        if expanded_right > raw_right:
            shift = expanded_right - raw_right
            expanded_left -= shift
            expanded_right -= shift

        body_left = max(raw_left, expanded_left)
        body_right = min(raw_right, body_left + desired)
        body_width = body_right - body_left

    if body_width <= 0:
        body_left = raw_left
        body_right = raw_right
        body_width = raw_width

    body_center_x = (body_left + body_right) / 2.0

    # AnimatedSprite2D uses a centred texture by default. Shifting the sprite
    # so the character's bottom-centre lands on the root origin makes
    # CollisionShape2D.position = (0, -H / 2) line up with the feet.
    sprite_offset_x = frame_width / 2.0 - body_center_x
    sprite_offset_y = frame_height / 2.0 - bottom
    collision_position_y = -height / 2.0

    shape_data: dict[str, Any]
    if shape_kind == "rectangle":
        shape_type = "RectangleShape2D"
        shape_data = {
            "type": shape_type,
            "size": [float(body_width), float(height)],
        }
        rotation = 0.0
        sub_resource = (
            '[sub_resource type="RectangleShape2D" id="RectangleShape2D_body"]\n'
            f"size = Vector2({_format_godot_float(body_width)}, "
            f"{_format_godot_float(height)})"
        )
    else:
        shape_type = "CapsuleShape2D"
        if body_width <= height:
            radius = body_width / 2.0
            capsule_height = float(height)
            rotation = 0.0
        else:
            # A vertical capsule cannot represent a body wider than it is tall.
            # Rotate it 90 degrees so wide slimes keep their full width and no
            # artificial height extension is required.
            radius = height / 2.0
            capsule_height = float(body_width)
            rotation = math.pi / 2.0
        shape_data = {
            "type": shape_type,
            "radius": float(radius),
            "height": float(capsule_height),
            "rotation": float(rotation),
        }
        sub_resource = (
            '[sub_resource type="CapsuleShape2D" id="CapsuleShape2D_body"]\n'
            f"radius = {_format_godot_float(radius)}\n"
            f"height = {_format_godot_float(capsule_height)}"
        )

    sub_resource_id = (
        "RectangleShape2D_body"
        if shape_kind == "rectangle"
        else "CapsuleShape2D_body"
    )
    node_lines = [
        '[node name="CollisionShape2D" type="CollisionShape2D" parent="."]'
    ]
    if abs(rotation) > 1e-9:
        node_lines.append(f"rotation = {_format_float(rotation)}")
    node_lines.extend(
        [
            f"position = Vector2(0.0, {_format_godot_float(collision_position_y)})",
            f'shape = SubResource("{sub_resource_id}")',
        ]
    )
    collision_node = "\n".join(node_lines)
    sprite_offset_property = (
        "offset = Vector2("
        f"{_format_godot_float(sprite_offset_x)}, "
        f"{_format_godot_float(sprite_offset_y)})"
    )

    return {
        "shape": shape_kind,
        "shape_type": shape_type,
        "frame_count": len(regions),
        "non_empty_frame_count": len(masks),
        "frame_width": int(frame_width),
        "frame_height": int(frame_height),
        "top": int(top),
        "bottom": int(bottom),
        "height": int(height),
        "width": float(body_width),
        "raw_width": int(raw_width),
        "raw_bounds": [int(raw_left), int(raw_right)],
        "body_bounds": [int(body_left), int(body_right)],
        "body_center_x": float(body_center_x),
        "sprite_offset": [float(sprite_offset_x), float(sprite_offset_y)],
        "sprite_offset_property": sprite_offset_property,
        "collision_position": [0.0, float(collision_position_y)],
        "collision_rotation": float(rotation),
        "size": [float(body_width), float(height)],
        "shape_data": shape_data,
        "sub_resource_snippet": sub_resource,
        "collision_node_snippet": collision_node,
        "tscn_snippet": sub_resource + "\n\n" + collision_node,
    }


def build_character_scene(
    project_root: str,
    image_path: str,
    sprite_frames_tres: str,
    output_tscn: str,
    collider_frames: list[dict],
    root_name: str = "Character",
    root_type: str = "CharacterBody2D",
    default_animation: str = "idle",
    shape: str = "rectangle",
    alpha_threshold: int = 10,
    thickness_ratio: float = 0.30,
) -> dict[str, Any]:
    """Write a complete Godot 4 ``.tscn`` character scene with AnimatedSprite2D and body collider.

    Combines an existing (or newly generated) ``SpriteFrames`` ``.tres``
    resource with a feet-aligned ``CollisionShape2D`` computed by
    :func:`build_body_collider` and writes a ready-to-open ``.tscn`` file.
    """

    root = Path(project_root).expanduser()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"project_root does not exist: {root}")
    root = root.resolve()

    raw_tres = str(sprite_frames_tres)
    if raw_tres.startswith("res://"):
        tres_candidate = root / raw_tres[len("res://") :]
    else:
        supplied_tres = Path(raw_tres).expanduser()
        tres_candidate = (
            supplied_tres if supplied_tres.is_absolute() else root / supplied_tres
        )
    _, tres_relative = _resolve_within_project(
        root, tres_candidate, label="sprite_frames_tres"
    )
    tres_uri = "res://" + tres_relative.as_posix()

    raw_out = str(output_tscn)
    if raw_out.startswith("res://"):
        out_candidate = root / raw_out[len("res://") :]
    else:
        supplied_out = Path(raw_out).expanduser()
        out_candidate = (
            supplied_out if supplied_out.is_absolute() else root / supplied_out
        )
    out_path = out_candidate.resolve()

    collider = build_body_collider(
        image_path=image_path,
        frames=collider_frames,
        shape=shape,
        alpha_threshold=alpha_threshold,
        thickness_ratio=thickness_ratio,
        project_root=str(root),
    )

    safe_root_name = re.sub(r'["\r\n]', "_", str(root_name).strip() or "Character")
    safe_root_type = re.sub(
        r"[^A-Za-z0-9_]", "", str(root_type).strip() or "CharacterBody2D"
    )
    anim_literal = _gd_string(str(default_animation).strip() or "idle")
    autoplay_escaped = (
        (str(default_animation).strip() or "idle")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
    )

    lines = [
        '[gd_scene load_steps=3 format=3]',
        "",
        f'[ext_resource type="SpriteFrames" path="{tres_uri}" id="1_frames"]',
        "",
        collider["sub_resource_snippet"],
        "",
        f'[node name="{safe_root_name}" type="{safe_root_type}"]',
        "",
        '[node name="AnimatedSprite2D" type="AnimatedSprite2D" parent="."]',
        'sprite_frames = ExtResource("1_frames")',
        f"animation = {anim_literal}",
        f'autoplay = "{autoplay_escaped}"',
        collider["sprite_offset_property"],
        "",
        collider["collision_node_snippet"],
        "",
    ]
    text = "\n".join(lines)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{out_path.name}.",
        suffix=".tmp",
        dir=str(out_path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp_name, out_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

    return {
        "output_tscn": str(out_path),
        "sprite_frames_res": tres_uri,
        "root_name": safe_root_name,
        "root_type": safe_root_type,
        "collider": collider,
    }

