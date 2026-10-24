"""Lightweight Godot 4 spritesheet tooling with an MCP interface."""

from __future__ import annotations

from .core import (
    build_body_collider,
    build_character_scene,
    build_sprite_frames,
    extract_collision_polygon,
    inspect_spritesheet,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "inspect_spritesheet",
    "build_sprite_frames",
    "extract_collision_polygon",
    "build_body_collider",
    "build_character_scene",
]
