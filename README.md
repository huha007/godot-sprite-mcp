# godot-sprite-mcp

[![CI](https://github.com/huha007/godot-sprite-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/huha007/godot-sprite-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](pyproject.toml)

**[English](README.md) | [简体中文](README_zh.md)**

A lightweight **Model Context Protocol (MCP) server & CLI for Godot 4.x** that slices 2D spritesheets, exports `SpriteFrames (.tres)` animations, computes feet-aligned body colliders (`CollisionShape2D`), and generates ready-to-open `.tscn` character scenes directly from PNG alpha channels.

![Animated Demo](docs/demo_animation.gif)

![Collider Comparison](docs/showcase_collider.png)

> *In the showcase above, even when computed across the broadsword attack row (`raw_width = 128px`), the **30% vertical thickness filter** automatically strips the 74px extended blade and keeps a stable `54×112px` torso collider, while preserving the wide `99×112px` body on the slime.*

## ✨ Features

| MCP Tool | Description |
| :--- | :--- |
| **`inspect_spritesheet`** | Auto-detects grid cells or irregular sprite islands from the PNG alpha channel (supports `res://` URIs). |
| **`build_sprite_frames`** | Generates Godot 4 (`format=3`) `SpriteFrames` `.tres` resources with `AtlasTexture` sub-resources. |
| **`build_body_collider`** | Overlays animation frames and uses a **30% vertical thickness filter** to generate a stable, feet-aligned `RectangleShape2D` / `CapsuleShape2D`. |
| **`build_character_scene`** | Writes a complete Godot 4 `.tscn` character scene (`CharacterBody2D` + `AnimatedSprite2D` + feet-aligned `CollisionShape2D`). |
| **`extract_collision_polygon`** | Traces and simplifies outer pixel contours into a `CollisionPolygon2D` (<= 24 vertices) for static props. |

---

## 🚀 Quick Start (MCP Configuration)

**Prerequisites:** Python 3.10+, Git, and [`uv`](https://docs.astral.sh/uv/) (for `uvx`).

Add `godot-sprite-mcp` to your AI coding client (`mcp.json` in Cursor, Claude Code, Windsurf, Cline, Claude Desktop, etc.):

### Option 1: Run directly from GitHub via `uvx`

```json
{
  "mcpServers": {
    "godot-sprite": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/huha007/godot-sprite-mcp",
        "godot-sprite-mcp"
      ]
    }
  }
}
```

### Option 2: Run from a local clone / Conda environment

```bash
git clone https://github.com/huha007/godot-sprite-mcp.git
cd godot-sprite-mcp
pip install -e .
```

```json
{
  "mcpServers": {
    "godot-sprite": {
      "command": "godot-sprite-mcp"
    }
  }
}
```
*(On Windows with a virtual/Conda environment not on global `PATH`, set `"command"` to the full path of `python.exe` and `"args": ["-m", "godot_sprite_mcp"]`.)*

---

## 💬 Example Prompts for Your AI Agent

Once configured, ask your AI assistant in natural language:

- *"Inspect `res://assets/knight_sheet.png` in project `D:/my_game`, create `res://resources/knight_frames.tres` with `idle`, `run`, and `attack` animations, and call `build_character_scene` to generate `res://Knight.tscn`."*
- *"Analyze `res://assets/slime.png` and build a `Slime.tscn` with a feet-aligned body `CollisionShape2D`."*

---

## 🛠️ CLI Usage (Standalone)

```bash
# 1. Inspect spritesheet layout (grid or islands)
godot-sprite-mcp inspect assets/knight_sheet.png --mode auto

# 2. Build Godot 4 SpriteFrames (.tres)
godot-sprite-mcp build \
  --project-root . \
  --image assets/knight_sheet.png \
  --animations @animations.json \
  --output res://resources/knight_frames.tres

# 3. Compute feet-aligned torso collider (RectangleShape2D / CapsuleShape2D)
godot-sprite-mcp body-collision assets/knight_sheet.png \
  --frames @idle_frames.json \
  --shape rectangle \
  --thickness-ratio 0.30

# 4. Extract contour polygon for static props
godot-sprite-mcp collision assets/rock.png --epsilon 2.0
```

## ⚠️ Scope & Limitations

- **PNG Alpha Channel Required:** Frame detection and contour/collider extraction rely on transparent backgrounds (`alpha <= alpha_threshold`). Solid-color opaque backgrounds must be made transparent first.
- **Grid vs. Islands Mode:** `mode="grid"` expects fully transparent horizontal/vertical gutters and uniform cell sizes; `mode="auto"` automatically falls back to 8-connected component `islands` when cells vary in size.
- **Movement Collider vs. Combat Hitboxes:** `build_body_collider` produces a single stable physics collider for character movement (`CharacterBody2D`), rather than per-frame animated melee attack hitboxes (`Area2D`).

## 🧪 Running Tests

```bash
pip install -e ".[dev]"
pytest -v
```

## 📄 License

[MIT](LICENSE)
