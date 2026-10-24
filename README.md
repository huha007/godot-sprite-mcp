# godot-sprite-mcp

**[English](README.md) | [简体中文](README_zh.md)**

A lightweight **Model Context Protocol (MCP) server & CLI for Godot 4.x** that slices 2D spritesheets, exports `SpriteFrames (.tres)` animations, and computes feet-aligned body colliders (`CollisionShape2D`) directly from PNG alpha channels.

![Animated Demo](docs/demo_animation.gif)

![Collider Comparison](docs/showcase_collider.png)

## ✨ Features

| MCP Tool | Description |
| :--- | :--- |
| **`inspect_spritesheet`** | Auto-detects grid cells or irregular sprite islands from the PNG alpha channel. |
| **`build_sprite_frames`** | Generates Godot 4 (`format=3`) `SpriteFrames` `.tres` resources with `AtlasTexture` sub-resources. |
| **`build_body_collider`** | Overlays animation frames and uses a **30% vertical thickness filter** to generate a stable, feet-aligned `RectangleShape2D` / `CapsuleShape2D` (automatically ignores thin extended weapons while preserving wide monsters like slimes). |
| **`extract_collision_polygon`** | Traces and simplifies outer pixel contours into a `CollisionPolygon2D` for static props. |

---

## 🚀 Quick Start (MCP Configuration)

Add `godot-sprite-mcp` to your AI coding client (`mcp.json` in Cursor, Claude Code, Windsurf, Cline, etc.):

### Option 1: Run directly from GitHub via `uvx` (Zero Install)

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

### Option 2: Run from a local clone

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

---

## 💬 Example Prompts for Your AI Agent

Once configured, simply ask your AI assistant in natural language:

- *"Inspect `res://assets/knight_sheet.png`, create a `SpriteFrames` resource with `idle`, `run`, and `attack` animations, and build a `Knight.tscn` character scene with a feet-aligned body collider."*
- *"Slice `res://assets/slime.png` and generate a `Slime.tscn` with a stable body `CollisionShape2D`."*

---

## 🛠️ CLI Usage (Standalone)

You can also use `godot-sprite-mcp` directly from the terminal or in CI/CD pipelines:

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

## 🧪 Running Tests

```bash
pip install -e ".[dev]"
pytest
```

## 📄 License

[MIT](LICENSE)
