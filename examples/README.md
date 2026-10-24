# Example assets

- `walk.png` — 128x32 transparent spritesheet with four 31x31 shapes inside
  four 32px frame slots (square, circle, triangle, diamond).
- `animations.json` — a ready-to-use `animations` array for `build_sprite_frames`.
- `player_sheet.png` — a 128x32 four-frame slime character sheet with a stable
  silhouette, used by the complete Godot demo.
- `godot_project/` — a minimal Godot 4.6 project containing the spritesheet,
  generated SpriteFrames resource, and a ready-to-open `player.tscn` scene.
- `Red/` — a complete 1188x792 character sheet with all 12 action sequences,
  a 124-frame SpriteFrames resource, and an animation browser scene.
- `Soldier/` — the Tiny RPG Soldier pack (100x100 cells, shadows included)
  with 7 animations, 43 frames, and a feet-aligned body collider.

## Try the Godot demo

Open the project directly with Godot 4.x:

```bat
"D:\godot\Godot_v4.6.2-stable_win64.exe" --path "D:\godot_mcp\examples\godot_project" --editor
```

Then double-click `player.tscn`:

- Select `AnimatedSprite2D` and use the SpriteFrames animation preview to play
  the four-frame `walk` animation.
- Select `CollisionShape2D` to inspect the stable 22x21 rectangle body collider.
- Press F6/F5 to run the scene; the `walk` animation autoplays.

The scene was assembled from the `.tres` produced by `build_sprite_frames` and
the feet-aligned body shape produced by `build_body_collider`. The older
`extract_collision_polygon` tool remains available for static objects.

## Inputs for MCP Inspector

`inspect_spritesheet`:

```json
{
  "image_path": "D:/godot_mcp/examples/walk.png",
  "alpha_threshold": 10,
  "mode": "auto"
}
```

Expected: `frame_count` is 4, `mode` is `grid`, and the frames start at
x = 0, 32, 64, 96 with sizes 31x31.

`build_sprite_frames`:

```json
{
  "project_root": "D:/godot_mcp/examples/godot_project",
  "image_path": "res://assets/walk.png",
  "animations": [
    {
      "name": "walk",
      "fps": 8.0,
      "loop": true,
      "frames": [
        {"x": 0, "y": 0, "w": 31, "h": 31},
        {"x": 32, "y": 0, "w": 31, "h": 31},
        {"x": 64, "y": 0, "w": 31, "h": 31},
        {"x": 96, "y": 0, "w": 31, "h": 31}
      ]
    }
  ],
  "output_tres": "res://resources/walk_frames.tres"
}
```

Expected: `load_steps` is 6 and `frame_count` is 4.

`extract_collision_polygon` (triangle frame):

```json
{
  "image_path": "D:/godot_mcp/examples/walk.png",
  "region": {"x": 64, "y": 0, "w": 31, "h": 31},
  "epsilon": 1.5,
  "centered": true
}
```

Expected: 3 vertices, with both positive and negative X/Y coordinates.
