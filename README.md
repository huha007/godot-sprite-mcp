# godot-sprite-mcp

A lightweight **Model Context Protocol (MCP) server and CLI for Godot 4.x**.
It turns spritesheets into Godot `SpriteFrames` resources, reports frame
layouts, and builds feet-aligned body colliders without requiring Godot, OpenCV,
or a browser.

- Python 3.10+
- Pure NumPy/Pillow image analysis
- Godot 4 resource syntax (`format=3`, `AtlasTexture`, `&"StringName"`)
- FastMCP server over stdio, plus a normal command-line interface
- Compatible with both MCP Python SDK 1.x (`FastMCP`) and 2.x (`MCPServer`)
- No proprietary formats: colours are read from the PNG alpha channel

## Features

| Tool | What it does |
| --- | --- |
| `inspect_spritesheet` | Detects grid cells or connected sprite islands and returns frame rectangles. |
| `build_sprite_frames` | Writes a Godot 4 `SpriteFrames` `.tres` resource with per-frame `AtlasTexture` sub-resources. |
| `build_body_collider` | Builds a stable, feet-aligned `RectangleShape2D`/`CapsuleShape2D` for moving characters. |
| `extract_collision_polygon` | Optional static-object tool: traces a contour and emits a `CollisionPolygon2D` snippet. |

## Installation

From this checkout:

```bash
python -m pip install -e .
# with test dependencies
python -m pip install -e ".[dev]"
```

The package exposes one console script:

```bash
godot-sprite-mcp --help
```

It can also be launched without a permanent install:

```bash
uvx --from . godot-sprite-mcp
```

The MCP server uses **stdio** and prints only JSON-RPC on that channel. Use the
CLI subcommands for human-readable JSON output.

## MCP client configuration

If `godot-sprite-mcp` is already on `PATH`:

```json
{
  "mcpServers": {
    "godot-sprite-mcp": {
      "command": "godot-sprite-mcp",
      "args": []
    }
  }
}
```

To run directly from a source checkout with `uv`:

```json
{
  "mcpServers": {
    "godot-sprite-mcp": {
      "command": "uvx",
      "args": ["--from", "D:/path/to/godot-sprite-mcp", "godot-sprite-mcp"]
    }
  }
}
```

No arguments are needed for normal use: the console script starts the stdio MCP
server by default. An explicit `serve` subcommand is also available:
`godot-sprite-mcp serve`.

## Tool reference

### `inspect_spritesheet`

```json
{
  "image_path": "D:/game/assets/player.png",
  "alpha_threshold": 10,
  "mode": "auto"
}
```

- `alpha_threshold` (default `10`): pixels with **alpha > threshold** are
  opaque.
- `mode`:
  - `"grid"` — projects opacity horizontally and vertically, finds fully
    transparent separator lines, and forms cells from the occupied projection
    bands. Every band must have the same width/height.
  - `"islands"` — 8-connected component labelling; returns a tight bounding box
    for every opaque island.
  - `"auto"` (default) — tries `"grid"` first. If band dimensions are
    inconsistent it falls back to `"islands"` automatically.

Example result:

```json
{
  "image_width": 104,
  "image_height": 68,
  "mode": "grid",
  "frame_count": 6,
  "frames": [
    {
      "id": 0,
      "x": 0,
      "y": 0,
      "w": 32,
      "h": 32,
      "pivot_bottom_center": [16.0, 32.0]
    },
    {
      "id": 1,
      "x": 36,
      "y": 0,
      "w": 32,
      "h": 32,
      "pivot_bottom_center": [52.0, 32.0]
    }
  ]
}
```

Frames are ordered **top-to-bottom (row-clustered), then left-to-right**, and
`id` values follow that final reading order.

> Grid detection relies on transparent gutters. If sprites touch each other
> across the full height/width of the sheet, there is no unambiguous grid
> boundary and `mode="islands"` is usually the better choice.

### `build_sprite_frames`

Input:

```json
{
  "project_root": "D:/game",
  "image_path": "D:/game/assets/player.png",
  "output_tres": "D:/game/resources/player_frames.tres",
  "animations": [
    {
      "name": "idle",
      "fps": 8.0,
      "loop": true,
      "frames": [
        {"x": 0, "y": 0, "w": 32, "h": 32},
        {"x": 32, "y": 0, "w": 32, "h": 32}
      ]
    },
    {
      "name": "attack",
      "fps": 13.0,
      "loop": false,
      "frames": [
        {"x": 64, "y": 0, "w": 32, "h": 32}
      ]
    }
  ]
}
```

- `image_path` may be absolute, relative to `project_root`, or a `res://` URI.
  It must resolve inside `project_root`; the generated texture reference is
  `res://...`.
- `output_tres` may be absolute, relative to `project_root`, or a `res://` URI.
  Parent directories are created automatically.
- Animation names must be unique.
- `fps` defaults to `10.0`, `loop` defaults to `true`, and a frame `duration`
  defaults to `1.0`. Playback timing is controlled by `speed`; `duration`
  remains available for per-frame overrides.
- Regions are validated against the real image dimensions. Out-of-bounds frames
  are rejected before anything is written.

Generated file shape:

```ini
[gd_resource type="SpriteFrames" load_steps=5 format=3]

[ext_resource type="Texture2D" path="res://assets/player.png" id="1_tex"]

[sub_resource type="AtlasTexture" id="AtlasTexture_idle_0"]
atlas = ExtResource("1_tex")
region = Rect2(0, 0, 32, 32)

[sub_resource type="AtlasTexture" id="AtlasTexture_idle_1"]
atlas = ExtResource("1_tex")
region = Rect2(32, 0, 32, 32)

[sub_resource type="AtlasTexture" id="AtlasTexture_attack_0"]
atlas = ExtResource("1_tex")
region = Rect2(64, 0, 32, 32)

[resource]
animations = [{
"frames": [{
"duration": 1.0,
"texture": SubResource("AtlasTexture_idle_0")
}, {
"duration": 1.0,
"texture": SubResource("AtlasTexture_idle_1")
}],
"loop": true,
"name": &"idle",
"speed": 8.0
}, {
"frames": [{
"duration": 1.0,
"texture": SubResource("AtlasTexture_attack_0")
}],
"loop": false,
"name": &"attack",
"speed": 13.0
}]
```

`load_steps` is exactly:

```text
1 ext_resource + number_of_AtlasTexture_sub_resources + 1 main resource
```

The return value from the tool includes:

```json
{
  "output_tres": "D:/game/resources/player_frames.tres",
  "texture_path": "res://assets/player.png",
  "load_steps": 5,
  "animation_count": 2,
  "frame_count": 3
}
```

### `build_body_collider`

Recommended collision tool for moving characters and monsters. It consumes all
frames of one animation, overlays their alpha masks, and produces one stable
body shape instead of a polygon that changes silhouette every frame.

```json
{
  "image_path": "D:/game/assets/player.png",
  "frames": [
    {"x": 0, "y": 264, "w": 66, "h": 66},
    {"x": 66, "y": 264, "w": 66, "h": 66}
  ],
  "shape": "rectangle",
  "alpha_threshold": 10,
  "thickness_ratio": 0.30
}
```

- `shape`: `"rectangle"` (default) or `"capsule"`.
- Frames in one sequence must share the same `w`/`h`.
- The character's overall `top`/`bottom` is measured across every frame.
  `H = bottom - top`.
- The aligned alpha masks are averaged. A column joins the core body only when
  its average vertical pixel count is at least `thickness_ratio * H`. This
  discards thin swords/arms while preserving wide slimes.
- If the filtered width is too narrow, it is expanded to at least
  `min(raw_W, 0.30 * H)`, never exceeding the raw non-transparent width
  `raw_W`. Width is not capped by height.
- The return value supplies a feet-at-origin setup:
  - `sprite_offset` to assign to `AnimatedSprite2D.offset`
  - `collision_position = (0, -H / 2)`
  - `RectangleShape2D` size or `CapsuleShape2D` radius/height
  - ready-to-paste `sub_resource_snippet` and `collision_node_snippet`

If a requested capsule is wider than it is tall (for example a slime), the
result uses the full width as capsule height and a 90-degree rotation, so it is
not squeezed into a humanoid aspect ratio.

Example result:

```json
{
  "shape_type": "RectangleShape2D",
  "top": 6,
  "bottom": 56,
  "height": 50,
  "width": 15.0,
  "raw_width": 48,
  "sprite_offset": [1.5, -23.0],
  "collision_position": [0.0, -25.0],
  "sub_resource_snippet": "[sub_resource type=\"RectangleShape2D\" id=\"RectangleShape2D_body\"]\nsize = Vector2(15.0, 50.0)",
  "collision_node_snippet": "[node name=\"CollisionShape2D\" type=\"CollisionShape2D\" parent=\".\"]\nposition = Vector2(0.0, -25.0)\nshape = SubResource(\"RectangleShape2D_body\")"
}
```

### `extract_collision_polygon` (optional, static objects)

This older polygon tool is retained for static props and irregular scenery. Use
it only when a contour-accurate `CollisionPolygon2D` is wanted; for moving
characters use `build_body_collider`.

```json
{
  "image_path": "D:/game/assets/player.png",
  "region": {"x": 0, "y": 0, "w": 32, "h": 32},
  "epsilon": 2.0,
  "centered": true
}
```

- `region` is optional. Coordinates are region-local in the returned polygon.
- `epsilon` is the RDP tolerance in pixels. Larger values produce fewer points.
  If a contour is still too detailed, the implementation progressively raises
  the tolerance so the final polygon has at most **24** vertices.
- `centered=true` matches Godot 4's `Sprite2D.centered = true` default:
  every point is shifted by `-w/2` and `-h/2`, where `w`/`h` are the region (or
  whole image) dimensions.
- `centered=false` keeps pixel-edge coordinates with a top-left origin.

Example result:

```json
{
  "points": [
    [-16.0, -12.0],
    [16.0, -12.0],
    [16.0, 12.0],
    [-16.0, 12.0]
  ],
  "vertex_count": 4,
  "packed_vector2_array": "PackedVector2Array(-16.0, -12.0, 16.0, -12.0, 16.0, 12.0, -16.0, 12.0)",
  "tscn_snippet": "[node name=\"CollisionPolygon2D\" type=\"CollisionPolygon2D\" parent=\".\"]\npolygon = PackedVector2Array(-16.0, -12.0, 16.0, -12.0, 16.0, 12.0, -16.0, 12.0)"
}
```

Paste `tscn_snippet` under a `Sprite2D` node in a `.tscn` scene. For example:

```ini
[node name="Player" type="Sprite2D"]
texture = ExtResource("1_tex")

[node name="CollisionPolygon2D" type="CollisionPolygon2D" parent="."]
polygon = PackedVector2Array(-16.0, -12.0, 16.0, -12.0, 16.0, 12.0, -16.0, 12.0)
```

Algorithm notes:

- The largest opaque connected contour is used; smaller disconnected details
  and interior holes are ignored for this single-polygon tool.
- Boundary tracing uses the pixel-edge graph, so a filled `32 x 32` region maps
  exactly to `0..32`, not a half-pixel-inset approximation.
- Boundaries are walked clockwise in screen coordinates (Godot's y-down space).
- Ramer-Douglas-Peucker simplification is followed by a self-intersection check.
  A convex-hull fallback guarantees a valid simple polygon in pathological
  cases.

## CLI examples

Inspect a sheet:

```bash
godot-sprite-mcp inspect assets/player.png --mode auto
```

Build a resource from an animation JSON file:

```bash
godot-sprite-mcp build \
  --project-root . \
  --image assets/player.png \
  --animations @animations.json \
  --output res://resources/player_frames.tres
```

Extract a collision polygon (optional, static objects):

```bash
godot-sprite-mcp collision assets/player.png \
  --region '{"x":0,"y":0,"w":32,"h":32}' \
  --epsilon 2.0
```

Build a stable body collider from an animation frame list:

```bash
godot-sprite-mcp body-collision assets/player.png \
  --frames @frames.json \
  --shape rectangle \
  --thickness-ratio 0.30
```

`--shape capsule` is also available. `frames.json` is a JSON array of the
selected animation's regions.

Use `--no-centered` to keep top-left pixel coordinates for the polygon tool.

## Project layout

```text
godot-sprite-mcp/
├── pyproject.toml
├── README.md
├── src/
│   └── godot_sprite_mcp/
│       ├── __init__.py
│       ├── __main__.py
│       ├── core.py
│       └── server.py
└── tests/
    └── test_pipeline.py
```

`core.py` has no MCP dependency and can be imported directly:

```python
from godot_sprite_mcp import inspect_spritesheet

layout = inspect_spritesheet("assets/player.png")
for frame in layout["frames"]:
    print(frame["id"], frame["x"], frame["y"], frame["w"], frame["h"])
```

## Development

```bash
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
# or
pytest
```

The tests generate their own PNGs, run the full inspection/build/collision
pipeline, and assert the Godot 4 resource syntax, path handling, coordinate
conversion, vertex limits, and error cases.

## License

MIT
