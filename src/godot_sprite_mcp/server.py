"""FastMCP server and command-line interface for godot-sprite-mcp."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

try:
    # MCP Python SDK 1.x.
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError as fastmcp_import_error:
    try:
        # MCP Python SDK 2.x renamed FastMCP to MCPServer. The small API
        # surface used here (name, @server.tool(), server.run()) is compatible.
        from mcp.server.mcpserver import MCPServer as FastMCP
    except ModuleNotFoundError:
        raise fastmcp_import_error

from . import __version__
from . import core

mcp = FastMCP("godot-sprite-mcp")


@mcp.tool()
def inspect_spritesheet(
    image_path: str,
    alpha_threshold: int = 10,
    mode: str = "auto",
    project_root: str | None = None,
) -> dict[str, Any]:
    """Inspect a PNG spritesheet and return frame rectangles.

    Use this tool before building animations when you need to discover the
    frame layout of a spritesheet. The alpha channel is analysed; pixels with
    alpha strictly greater than ``alpha_threshold`` count as opaque.

    Args:
        image_path: Absolute path, relative path, or ``res://...`` URI to the
            source PNG.
        alpha_threshold: Opaque-pixel cutoff in the inclusive range 0..255.
            Defaults to 10, so nearly transparent antialiasing is ignored.
        mode: Detection strategy:
            "grid" finds fully transparent horizontal/vertical separator lines,
            "islands" finds 8-connected opaque islands and their tight bounding
            boxes, and "auto" tries "grid" first and falls back to "islands"
            when cell sizes are not uniform.
        project_root: Optional Godot project root directory used to resolve
            ``res://`` URIs or relative paths.

    Returns:
        A JSON-compatible dictionary with ``image_width``, ``image_height``,
        the detected ``mode``, ``frame_count``, and ``frames``. Every frame is
        ``{"id": int, "x": int, "y": int, "w": int, "h": int,
        "pivot_bottom_center": [float, float]}``. Frames are ordered top to
        bottom (row-clustered), then left to right.
    """

    return core.inspect_spritesheet(
        image_path=image_path,
        alpha_threshold=alpha_threshold,
        mode=mode,
        project_root=project_root,
    )


@mcp.tool()
def build_sprite_frames(
    project_root: str,
    image_path: str,
    animations: list[dict],
    output_tres: str,
) -> dict[str, Any]:
    """Create a Godot 4.x SpriteFrames .tres resource from atlas regions.

    This writes a ``format=3`` Godot 4 resource. The image must live inside
    ``project_root`` because Godot needs a ``res://`` URI. Each animation
    becomes an entry in the SpriteFrames ``animations`` array, and each frame
    becomes an ``AtlasTexture`` sub-resource referencing the image.

    Args:
        project_root: Absolute path to the Godot project directory (the folder
            containing ``project.godot``).
        image_path: Path to the spritesheet. It may be absolute, relative to
            the project root, or already written as ``res://...``. It must be
            inside ``project_root``.
        animations: List of animation dictionaries. Example:
            ``[{"name": "idle", "fps": 10.0, "loop": True, "frames": [
            {"x": 0, "y": 0, "w": 32, "h": 32},
            {"x": 32, "y": 0, "w": 32, "h": 32}]}]``.
            Every animation requires a unique ``name`` and a ``frames`` list.
            ``fps`` defaults to 10.0 and ``loop`` defaults to true. An optional
            per-frame ``duration`` defaults to 1.0; playback timing is normally
            controlled by the animation speed.
        output_tres: Destination .tres path. An absolute path or ``res://`` URI
            is recommended; a relative path is resolved against
            ``project_root``. Parent directories are created automatically.

    Returns:
        Metadata including the absolute ``output_tres`` path, the Godot
        ``texture_path`` URI, ``load_steps``, ``animation_count`` and
        ``frame_count``.
    """

    return core.build_sprite_frames(
        project_root=project_root,
        image_path=image_path,
        animations=animations,
        output_tres=output_tres,
    )


@mcp.tool()
def extract_collision_polygon(
    image_path: str,
    region: dict | None = None,
    epsilon: float = 2.0,
    centered: bool = True,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Extract a simplified outer collision polygon from opaque pixels.

    This optional tool is intended for static objects and irregular scenery.
    For moving characters and monsters, use build_body_collider instead to get
    a stable feet-aligned RectangleShape2D or CapsuleShape2D.

    The largest external alpha contour is traced and simplified with the
    Ramer-Douglas-Peucker algorithm. The result is a simple clockwise polygon
    with at most 24 vertices, suitable for a CollisionPolygon2D.

    Args:
        image_path: Absolute path, relative path, or ``res://`` URI to a PNG.
        region: Optional sub-region ``{"x": int, "y": int, "w": int, "h": int}``
            in image pixels. When omitted, the whole image is used. Returned
            coordinates are relative to this region's top-left corner.
        epsilon: RDP simplification tolerance in pixels. Defaults to 2.0.
            Larger values produce fewer vertices. If necessary the tolerance
            is increased internally to keep the polygon at or below 24
            vertices.
        centered: When true (the default, matching Godot 4 Sprite2D), every
            point is shifted so the coordinate origin is the image/region
            centre. For a region of size ``w x h`` the conversion is
            ``x - w / 2`` and ``y - h / 2``. Set to false to keep pixel-space
            coordinates with a top-left origin.
        project_root: Optional Godot project root directory for resolving
            ``res://`` URIs.

    Returns:
        A dictionary with ``points`` (list of [x, y]), ``vertex_count``,
        ``packed_vector2_array`` (Godot text such as
        ``PackedVector2Array(0.0, -16.0, ...)``) and ``tscn_snippet`` (a
        CollisionPolygon2D node block ready to paste into a .tscn file).
    """

    return core.extract_collision_polygon(
        image_path=image_path,
        region=region,
        epsilon=epsilon,
        centered=centered,
        project_root=project_root,
    )


@mcp.tool()
def build_body_collider(
    image_path: str,
    frames: list[dict],
    shape: str = "rectangle",
    alpha_threshold: int = 10,
    thickness_ratio: float = 0.30,
    project_root: str | None = None,
) -> dict[str, Any]:
    """Build a stable single-shape body collider for a moving character.

    This is the recommended collision tool for player/enemy movement. It
    consumes all frames of one animation, overlays their alpha masks, measures
    the full character height and a thickness-filtered body width, and returns
    a feet-aligned RectangleShape2D (default) or CapsuleShape2D. The older
    extract_collision_polygon tool remains available for static objects.

    Args:
        image_path: Path or ``res://`` URI to the spritesheet image.
        frames: Every frame region of the selected animation, for example
            ``[{"x": 0, "y": 264, "w": 66, "h": 66}, ...]``. All frames must
            have the same width and height.
        shape: ``"rectangle"`` (default) or ``"capsule"``. Wide bodies such as
            slimes use a rotated capsule automatically when capsule is chosen.
        alpha_threshold: Pixels with alpha strictly greater than this are
            opaque. Defaults to 10.
        thickness_ratio: A column must have at least this fraction of the
            character height to count as core body. Defaults to 0.30, which
            filters thin weapons and arms.
        project_root: Optional Godot project root directory for resolving
            ``res://`` URIs.

    Returns:
        A JSON-compatible dictionary containing height/top/bottom, filtered
        body width and raw width, ``sprite_offset`` for the AnimatedSprite2D,
        ``collision_position`` (feet at origin), shape parameters, and
        ready-to-paste sub-resource and CollisionShape2D snippets.
    """

    return core.build_body_collider(
        image_path=image_path,
        frames=frames,
        shape=shape,
        alpha_threshold=alpha_threshold,
        thickness_ratio=thickness_ratio,
        project_root=project_root,
    )


@mcp.tool()
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
    """Write a complete Godot 4 .tscn character scene with AnimatedSprite2D and feet-aligned body collider.

    Args:
        project_root: Path to the Godot project directory containing ``project.godot``.
        image_path: Path or ``res://`` URI to the spritesheet PNG.
        sprite_frames_tres: Path or ``res://`` URI to the generated SpriteFrames ``.tres`` resource.
        output_tscn: Destination ``.tscn`` file path or ``res://`` URI.
        collider_frames: Frame regions (typically the idle animation row) used to compute the body collider.
        root_name: Root node name in the scene (default: ``"Character"``).
        root_type: Root node Godot class (default: ``"CharacterBody2D"``).
        default_animation: Default animation name for the AnimatedSprite2D (default: ``"idle"``).
        shape: ``"rectangle"`` (default) or ``"capsule"``.
        alpha_threshold: Opaque alpha cutoff 0..255 (default: 10).
        thickness_ratio: Minimum vertical column thickness ratio (default: 0.30).

    Returns:
        Metadata including the written ``output_tscn`` path, ``sprite_frames_res`` URI, and ``collider`` details.
    """

    return core.build_character_scene(
        project_root=project_root,
        image_path=image_path,
        sprite_frames_tres=sprite_frames_tres,
        output_tscn=output_tscn,
        collider_frames=collider_frames,
        root_name=root_name,
        root_type=root_type,
        default_animation=default_animation,
        shape=shape,
        alpha_threshold=alpha_threshold,
        thickness_ratio=thickness_ratio,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_json_argument(raw_value: str, option_name: str) -> Any:
    """Parse an inline JSON argument or read it from ``@path``."""

    if raw_value.startswith("@"):
        source = Path(raw_value[1:]).expanduser()
        try:
            raw_value = source.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise ValueError(f"Could not read {option_name} file {source}: {exc}") from exc

    try:
        return json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{option_name} must be valid JSON (or @path to a JSON file): {exc}"
        ) from exc


def _print_json(value: Any) -> None:
    json.dump(value, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="godot-sprite-mcp",
        description=(
            "MCP server and CLI for inspecting Godot 4 spritesheets, exporting "
            "SpriteFrames .tres resources, building body colliders, and "
            "extracting static collision polygons."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "serve",
        help="Run the MCP server over stdio (default when no command is given).",
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect a spritesheet and print frame rectangles as JSON.",
    )
    inspect_parser.add_argument("image", help="Path to the spritesheet image.")
    inspect_parser.add_argument(
        "--alpha-threshold",
        type=int,
        default=10,
        help="Opaque alpha cutoff, 0-255 (default: 10).",
    )
    inspect_parser.add_argument(
        "--mode",
        choices=("auto", "grid", "islands"),
        default="auto",
        help="Frame-detection strategy (default: auto).",
    )

    build_parser = subparsers.add_parser(
        "build",
        help="Build a Godot 4 SpriteFrames .tres resource.",
    )
    build_parser.add_argument("--project-root", required=True)
    build_parser.add_argument("--image", required=True)
    build_parser.add_argument(
        "--animations",
        required=True,
        help="Animation JSON, or @path/to/animations.json.",
    )
    build_parser.add_argument(
        "--output",
        required=True,
        help="Destination .tres path (absolute, relative to project root, or res://).",
    )

    collision_parser = subparsers.add_parser(
        "collision",
        help="Extract a CollisionPolygon2D polygon from an image region.",
    )
    collision_parser.add_argument("image", help="Path to the source image.")
    collision_parser.add_argument(
        "--region",
        default=None,
        help='Optional region JSON: {"x":0,"y":0,"w":32,"h":32}.',
    )
    collision_parser.add_argument(
        "--epsilon",
        type=float,
        default=2.0,
        help="RDP simplification tolerance in pixels (default: 2.0).",
    )
    collision_parser.add_argument(
        "--no-centered",
        action="store_false",
        dest="centered",
        help="Keep top-left pixel coordinates instead of Sprite2D-centred ones.",
    )
    collision_parser.set_defaults(centered=True)

    body_parser = subparsers.add_parser(
        "body-collision",
        help=(
            "Build a stable RectangleShape2D/CapsuleShape2D body collider "
            "from an animation sequence."
        ),
    )
    body_parser.add_argument("image", help="Path to the source image.")
    body_parser.add_argument(
        "--frames",
        required=True,
        help="JSON array of frame regions, or @path/to/frames.json.",
    )
    body_parser.add_argument(
        "--shape",
        choices=("rectangle", "capsule"),
        default="rectangle",
        help="Collision shape type (default: rectangle).",
    )
    body_parser.add_argument(
        "--alpha-threshold",
        type=int,
        default=10,
        help="Opaque alpha cutoff, 0-255 (default: 10).",
    )
    body_parser.add_argument(
        "--thickness-ratio",
        type=float,
        default=0.30,
        help="Minimum vertical thickness ratio for core body columns (default: 0.30).",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Entry point for the ``godot-sprite-mcp`` console script."""

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command in (None, "serve"):
        # FastMCP's default transport is stdio, which is what MCP clients use.
        mcp.run()
        return

    try:
        if args.command == "inspect":
            result = core.inspect_spritesheet(
                image_path=args.image,
                alpha_threshold=args.alpha_threshold,
                mode=args.mode,
            )
        elif args.command == "build":
            animations = _load_json_argument(args.animations, "--animations")
            if not isinstance(animations, list):
                raise ValueError("--animations JSON must be a list")
            result = core.build_sprite_frames(
                project_root=args.project_root,
                image_path=args.image,
                animations=animations,
                output_tres=args.output,
            )
        elif args.command == "collision":
            region = (
                None
                if args.region is None
                else _load_json_argument(args.region, "--region")
            )
            if region is not None and not isinstance(region, dict):
                raise ValueError("--region JSON must be an object")
            result = core.extract_collision_polygon(
                image_path=args.image,
                region=region,
                epsilon=args.epsilon,
                centered=args.centered,
            )
        elif args.command == "body-collision":
            frames = _load_json_argument(args.frames, "--frames")
            if not isinstance(frames, list):
                raise ValueError("--frames JSON must be a list")
            result = core.build_body_collider(
                image_path=args.image,
                frames=frames,
                shape=args.shape,
                alpha_threshold=args.alpha_threshold,
                thickness_ratio=args.thickness_ratio,
            )
        else:  # pragma: no cover - argparse rejects unknown commands.
            parser.error(f"unknown command: {args.command}")
            return
    except (OSError, TypeError, ValueError) as exc:
        parser.exit(status=1, message=f"godot-sprite-mcp: error: {exc}\n")
        return

    _print_json(result)


if __name__ == "__main__":
    main()
