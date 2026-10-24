"""End-to-end tests for godot-sprite-mcp.

The tests create their own PNG fixtures, run the public pipeline functions,
and inspect the generated Godot text resources.  They intentionally use only
the standard-library unittest runner so they can also be run with pytest.
"""

from __future__ import annotations

import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from godot_sprite_mcp.core import (  # noqa: E402
    build_body_collider,
    build_character_scene,
    build_sprite_frames,
    extract_collision_polygon,
    inspect_spritesheet,
)


_ARTIFACT_ROOT = Path(__file__).resolve().parent / "_artifacts"


def _rgba(width: int, height: int) -> Image.Image:
    return Image.new("RGBA", (width, height), (0, 0, 0, 0))


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        _ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp_dir = _ARTIFACT_ROOT / uuid.uuid4().hex
        self.temp_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # inspect_spritesheet
    # ------------------------------------------------------------------

    def test_inspect_regular_grid(self) -> None:
        sheet = _rgba(104, 68)
        draw = ImageDraw.Draw(sheet)
        for row in range(2):
            for column in range(3):
                x = column * 36
                y = row * 36
                draw.rectangle(
                    [x, y, x + 31, y + 31],
                    fill=(20, 80 + row * 30, 200, 255),
                )
        image_path = self.temp_dir / "grid.png"
        sheet.save(image_path)

        result = inspect_spritesheet(str(image_path))

        self.assertEqual(result["image_width"], 104)
        self.assertEqual(result["image_height"], 68)
        self.assertEqual(result["mode"], "grid")
        self.assertEqual(result["frame_count"], 6)
        expected_positions = [
            (0, 0),
            (36, 0),
            (72, 0),
            (0, 36),
            (36, 36),
            (72, 36),
        ]
        for index, (expected_x, expected_y) in enumerate(expected_positions):
            frame = result["frames"][index]
            self.assertEqual(frame["id"], index)
            self.assertEqual((frame["x"], frame["y"]), (expected_x, expected_y))
            self.assertEqual((frame["w"], frame["h"]), (32, 32))
            self.assertEqual(
                frame["pivot_bottom_center"],
                [expected_x + 16.0, expected_y + 32.0],
            )

        json.dumps(result)  # The public result must be JSON serializable.

    def test_auto_falls_back_to_islands_and_sorts_rows(self) -> None:
        image = _rgba(120, 80)
        draw = ImageDraw.Draw(image)
        # Deliberately unequal widths and heights prevent a regular grid.
        draw.rectangle([5, 8, 24, 19], fill=(255, 0, 0, 255))
        draw.rectangle([70, 6, 83, 23], fill=(0, 255, 0, 255))
        draw.rectangle([10, 50, 21, 59], fill=(0, 0, 255, 255))
        draw.rectangle([65, 47, 84, 66], fill=(255, 255, 0, 255))
        image_path = self.temp_dir / "islands.png"
        image.save(image_path)

        result = inspect_spritesheet(str(image_path), mode="auto")

        self.assertEqual(result["mode"], "islands")
        self.assertEqual(result["frame_count"], 4)
        # Top row is sorted left-to-right, followed by the bottom row.
        self.assertEqual(
            [(frame["x"], frame["y"], frame["w"], frame["h"])
             for frame in result["frames"]],
            [
                (5, 8, 20, 12),
                (70, 6, 14, 18),
                (10, 50, 12, 10),
                (65, 47, 20, 20),
            ],
        )
        for index, frame in enumerate(result["frames"]):
            self.assertEqual(frame["id"], index)

    def test_islands_join_diagonal_pixels(self) -> None:
        sheet = _rgba(20, 20)
        pixels = np.asarray(sheet).copy()
        pixels[2, 2] = [255, 255, 255, 255]
        pixels[3, 3] = [255, 255, 255, 255]
        image_path = self.temp_dir / "diagonal.png"
        Image.fromarray(pixels, mode="RGBA").save(image_path)

        result = inspect_spritesheet(str(image_path), mode="islands")

        self.assertEqual(result["frame_count"], 1)
        self.assertEqual(
            (result["frames"][0]["x"], result["frames"][0]["y"],
             result["frames"][0]["w"], result["frames"][0]["h"]),
            (2, 2, 2, 2),
        )

    def test_alpha_threshold_is_strict(self) -> None:
        sheet = _rgba(8, 8)
        pixels = np.asarray(sheet).copy()
        pixels[2:5, 2:5] = [255, 0, 0, 10]
        image_path = self.temp_dir / "alpha.png"
        Image.fromarray(pixels, mode="RGBA").save(image_path)

        with self.assertRaises(ValueError):
            inspect_spritesheet(str(image_path), alpha_threshold=10)

        result = inspect_spritesheet(str(image_path), alpha_threshold=9)
        self.assertEqual(result["frame_count"], 1)
        self.assertEqual(result["mode"], "grid")

    def test_grid_mode_rejects_irregular_sheet(self) -> None:
        image = _rgba(80, 40)
        draw = ImageDraw.Draw(image)
        draw.rectangle([2, 2, 12, 20], fill=(255, 255, 255, 255))
        draw.rectangle([40, 2, 70, 20], fill=(255, 255, 255, 255))
        image_path = self.temp_dir / "irregular.png"
        image.save(image_path)

        with self.assertRaises(ValueError):
            inspect_spritesheet(str(image_path), mode="grid")

    # ------------------------------------------------------------------
    # build_sprite_frames
    # ------------------------------------------------------------------

    def test_build_sprite_frames_uses_godot4_syntax(self) -> None:
        project = self.temp_dir / "project"
        assets = project / "assets"
        assets.mkdir(parents=True)
        sheet = _rgba(64, 32)
        draw = ImageDraw.Draw(sheet)
        draw.rectangle([0, 0, 31, 31], fill=(255, 0, 0, 255))
        draw.rectangle([32, 0, 63, 31], fill=(0, 0, 255, 255))
        image_path = assets / "player sheet.png"
        sheet.save(image_path)

        animations = [
            {
                "name": "idle",
                "fps": 8.0,
                "loop": True,
                "frames": [
                    {"x": 0, "y": 0, "w": 32, "h": 32},
                    {"x": 32, "y": 0, "w": 32, "h": 32},
                ],
            },
            {
                "name": "attack",
                "fps": 13,
                "loop": False,
                "frames": [{"x": 0, "y": 0, "w": 32, "h": 32}],
            },
        ]
        output_path = project / "resources" / "player_frames.tres"

        result = build_sprite_frames(
            project_root=str(project),
            image_path=str(image_path),
            animations=animations,
            output_tres=str(output_path),
        )

        self.assertTrue(output_path.is_file())
        self.assertEqual(result["load_steps"], 5)  # 1 texture + 3 atlases + 1
        self.assertEqual(result["animation_count"], 2)
        self.assertEqual(result["frame_count"], 3)
        self.assertEqual(
            result["texture_path"], "res://assets/player sheet.png"
        )

        text = output_path.read_text(encoding="utf-8")
        self.assertTrue(
            text.startswith(
                '[gd_resource type="SpriteFrames" load_steps=5 format=3]\n'
            )
        )
        self.assertIn(
            '[ext_resource type="Texture2D" '
            'path="res://assets/player sheet.png" id="1_tex"]',
            text,
        )
        self.assertIn(
            '[sub_resource type="AtlasTexture" '
            'id="AtlasTexture_idle_0"]\n'
            'atlas = ExtResource("1_tex")\n'
            "region = Rect2(0, 0, 32, 32)",
            text,
        )
        self.assertIn(
            '[sub_resource type="AtlasTexture" '
            'id="AtlasTexture_attack_0"]',
            text,
        )
        self.assertIn('"name": &"idle"', text)
        self.assertIn('"name": &"attack"', text)
        self.assertIn('"loop": true', text)
        self.assertIn('"loop": false', text)
        self.assertIn('"speed": 8.0', text)
        self.assertIn('"speed": 13.0', text)
        self.assertIn('"duration": 1.0', text)
        self.assertIn('"frames": [{\n"duration": 1.0,', text)
        self.assertIn('}, {\n"duration": 1.0,', text)
        self.assertNotIn('"frames": [\n', text)
        # Godot 3 resource styles must not leak into format=3 output.
        self.assertNotIn("[gd_scene", text)
        self.assertNotIn("PoolVector2Array", text)
        self.assertNotIn("ExtResource( 1 )", text)

    def test_build_supports_res_paths_and_relative_output(self) -> None:
        project = self.temp_dir / "game"
        (project / "art").mkdir(parents=True)
        _rgba(16, 16).save(project / "art" / "icon.png")

        result = build_sprite_frames(
            project_root=str(project),
            image_path="res://art/icon.png",
            animations=[
                {
                    "name": "spin",
                    "fps": 4,
                    "loop": True,
                    "frames": [{"x": 0, "y": 0, "w": 16, "h": 16}],
                }
            ],
            output_tres="res://generated/spin.tres",
        )

        output_path = project / "generated" / "spin.tres"
        self.assertTrue(output_path.is_file())
        self.assertEqual(result["load_steps"], 3)
        self.assertIn(
            'path="res://art/icon.png"',
            output_path.read_text(encoding="utf-8"),
        )

    def test_build_rejects_image_outside_project(self) -> None:
        project = self.temp_dir / "project"
        project.mkdir()
        outside = self.temp_dir / "outside.png"
        _rgba(8, 8).save(outside)

        with self.assertRaises(ValueError):
            build_sprite_frames(
                project_root=str(project),
                image_path=str(outside),
                animations=[
                    {
                        "name": "idle",
                        "fps": 10,
                        "loop": True,
                        "frames": [{"x": 0, "y": 0, "w": 8, "h": 8}],
                    }
                ],
                output_tres=str(project / "idle.tres"),
            )

    def test_build_rejects_out_of_bounds_frames(self) -> None:
        project = self.temp_dir / "project"
        project.mkdir()
        _rgba(16, 16).save(project / "sheet.png")

        with self.assertRaises(ValueError):
            build_sprite_frames(
                project_root=str(project),
                image_path="sheet.png",
                animations=[
                    {
                        "name": "bad",
                        "fps": 10,
                        "loop": True,
                        "frames": [{"x": 8, "y": 8, "w": 16, "h": 16}],
                    }
                ],
                output_tres="bad.tres",
            )

    # ------------------------------------------------------------------
    # extract_collision_polygon
    # ------------------------------------------------------------------

    def test_collision_rectangle_is_centered_and_simplified(self) -> None:
        sheet = _rgba(64, 64)
        pixels = np.asarray(sheet).copy()
        pixels[20:44, 16:48] = [255, 255, 255, 255]
        image_path = self.temp_dir / "rectangle.png"
        Image.fromarray(pixels, mode="RGBA").save(image_path)

        result = extract_collision_polygon(str(image_path), epsilon=2.0)

        self.assertEqual(result["vertex_count"], 4)
        self.assertEqual(
            result["points"],
            [
                [-16.0, -12.0],
                [16.0, -12.0],
                [16.0, 12.0],
                [-16.0, 12.0],
            ],
        )
        self.assertEqual(
            result["packed_vector2_array"],
            "PackedVector2Array(-16.0, -12.0, 16.0, -12.0, "
            "16.0, 12.0, -16.0, 12.0)",
        )
        self.assertIn(
            '[node name="CollisionPolygon2D" type="CollisionPolygon2D" '
            'parent="."]',
            result["tscn_snippet"],
        )
        self.assertIn("polygon = PackedVector2Array(", result["tscn_snippet"])

    def test_collision_region_is_region_local(self) -> None:
        sheet = _rgba(100, 80)
        pixels = np.asarray(sheet).copy()
        pixels[20:35, 15:35] = [255, 0, 0, 255]
        image_path = self.temp_dir / "region.png"
        Image.fromarray(pixels, mode="RGBA").save(image_path)

        region = {"x": 10, "y": 15, "w": 40, "h": 30}
        centered = extract_collision_polygon(str(image_path), region=region)
        self.assertEqual(
            centered["points"],
            [
                [-15.0, -10.0],
                [5.0, -10.0],
                [5.0, 5.0],
                [-15.0, 5.0],
            ],
        )

        pixel_space = extract_collision_polygon(
            str(image_path), region=region, centered=False
        )
        self.assertEqual(
            pixel_space["points"],
            [[5.0, 5.0], [25.0, 5.0], [25.0, 20.0], [5.0, 20.0]],
        )

    def test_collision_uses_largest_component_and_stays_simple(self) -> None:
        sheet = _rgba(96, 96)
        draw = ImageDraw.Draw(sheet)
        draw.rectangle([5, 5, 14, 14], fill=(255, 255, 255, 255))
        # A large L shape with a concave corner.
        draw.rectangle([25, 20, 70, 38], fill=(255, 0, 0, 255))
        draw.rectangle([25, 38, 42, 75], fill=(255, 0, 0, 255))
        image_path = self.temp_dir / "large_l.png"
        sheet.save(image_path)

        result = extract_collision_polygon(
            str(image_path), epsilon=1.0, centered=False
        )

        self.assertGreaterEqual(result["vertex_count"], 4)
        self.assertLessEqual(result["vertex_count"], 24)
        # The largest component's top-left corner must be part of the result.
        self.assertIn([25.0, 20.0], result["points"])
        self.assertNotIn([5.0, 5.0], result["points"])

    def test_collision_respects_vertex_cap(self) -> None:
        sheet = _rgba(128, 128)
        draw = ImageDraw.Draw(sheet)
        # A connected comb: many narrow teeth on a solid base. At a tiny
        # epsilon its raw contour has far more than 24 vertices.
        draw.rectangle([10, 88, 110, 103], fill=(255, 255, 255, 255))
        for x in range(10, 110, 6):
            draw.rectangle([x, 20, x + 2, 88], fill=(255, 255, 255, 255))
        image_path = self.temp_dir / "teeth.png"
        sheet.save(image_path)

        result = extract_collision_polygon(
            str(image_path), epsilon=0.0, centered=False
        )

        self.assertLessEqual(result["vertex_count"], 24)
        self.assertGreaterEqual(result["vertex_count"], 4)

    def test_collision_rejects_empty_region(self) -> None:
        sheet = _rgba(16, 16)
        image_path = self.temp_dir / "empty.png"
        sheet.save(image_path)

        with self.assertRaises(ValueError):
            extract_collision_polygon(str(image_path))

    # ------------------------------------------------------------------
    # build_body_collider
    # ------------------------------------------------------------------

    def test_body_collider_filters_thin_weapons_and_aligns_feet(self) -> None:
        pixels = np.zeros((64, 240, 4), dtype=np.uint8)
        for frame in range(3):
            ox = frame * 80
            # Stable 20x48 body.
            pixels[16:64, ox + 30 : ox + 50] = [200, 50, 70, 255]
            # Thin sword in two frames only: 5px tall, far outside the body.
            if frame < 2:
                pixels[44:49, ox + 5 : ox + 30] = [240, 230, 210, 255]
        # A thin antenna changes the top of the overall sequence.
        pixels[10:16, 80 + 39 : 80 + 42] = [240, 230, 210, 255]

        image_path = self.temp_dir / "body_filter.png"
        Image.fromarray(pixels, mode="RGBA").save(image_path)
        frames = [
            {"x": index * 80, "y": 0, "w": 80, "h": 64}
            for index in range(3)
        ]

        result = build_body_collider(
            str(image_path), frames, shape="rectangle"
        )

        self.assertEqual(result["frame_count"], 3)
        self.assertEqual(result["top"], 10)
        self.assertEqual(result["bottom"], 64)
        self.assertEqual(result["height"], 54)
        self.assertEqual(result["raw_width"], 45)
        self.assertEqual(result["width"], 20.0)
        self.assertAlmostEqual(result["sprite_offset"][0], 0.0)
        self.assertAlmostEqual(result["sprite_offset"][1], -32.0)
        self.assertEqual(result["collision_position"], [0.0, -27.0])
        self.assertEqual(result["size"], [20.0, 54.0])
        self.assertIn(
            '[sub_resource type="RectangleShape2D" '
            'id="RectangleShape2D_body"]',
            result["sub_resource_snippet"],
        )
        self.assertIn("size = Vector2(20.0, 54.0)", result["sub_resource_snippet"])
        self.assertIn(
            "position = Vector2(0.0, -27.0)",
            result["collision_node_snippet"],
        )
        self.assertEqual(
            result["sprite_offset_property"],
            "offset = Vector2(0.0, -32.0)",
        )

        capsule = build_body_collider(
            str(image_path), frames, shape="capsule"
        )
        self.assertEqual(capsule["shape_type"], "CapsuleShape2D")
        self.assertAlmostEqual(capsule["shape_data"]["radius"], 10.0)
        self.assertAlmostEqual(capsule["shape_data"]["height"], 54.0)
        self.assertAlmostEqual(capsule["shape_data"]["rotation"], 0.0)

    def test_body_collider_supports_wide_slime_capsule(self) -> None:
        pixels = np.zeros((40, 100, 4), dtype=np.uint8)
        pixels[10:40, 5:95] = [60, 190, 140, 255]

        image_path = self.temp_dir / "wide_slime.png"
        Image.fromarray(pixels, mode="RGBA").save(image_path)
        frames = [{"x": 0, "y": 0, "w": 100, "h": 40}]

        result = build_body_collider(
            str(image_path), frames, shape="capsule"
        )

        self.assertEqual(result["shape_type"], "CapsuleShape2D")
        self.assertEqual(result["height"], 30)
        self.assertEqual(result["width"], 90.0)
        self.assertGreater(result["width"], result["height"])
        self.assertAlmostEqual(result["shape_data"]["radius"], 15.0)
        self.assertAlmostEqual(result["shape_data"]["height"], 90.0)
        self.assertAlmostEqual(
            result["shape_data"]["rotation"], 1.5707963267948966
        )
        self.assertEqual(result["collision_position"], [0.0, -15.0])
        self.assertIn(
            '[sub_resource type="CapsuleShape2D" id="CapsuleShape2D_body"]',
            result["sub_resource_snippet"],
        )
        self.assertIn(
            "rotation = 1.570796", result["collision_node_snippet"]
        )

    def test_body_collider_enforces_minimum_width_floor(self) -> None:
        pixels = np.zeros((64, 160, 4), dtype=np.uint8)
        for frame in range(2):
            ox = frame * 80
            # 5px-wide torso, 60px tall.
            pixels[2:62, ox + 40 : ox + 45] = [200, 80, 80, 255]
            # 9px-thick wings fail the 30% vertical filter but define raw_W.
            pixels[30:39, ox + 5 : ox + 40] = [240, 240, 240, 255]
            pixels[30:39, ox + 45 : ox + 75] = [240, 240, 240, 255]

        image_path = self.temp_dir / "body_floor.png"
        Image.fromarray(pixels, mode="RGBA").save(image_path)
        frames = [
            {"x": index * 80, "y": 0, "w": 80, "h": 64}
            for index in range(2)
        ]

        result = build_body_collider(str(image_path), frames, shape="rectangle")

        self.assertEqual(result["height"], 60)
        self.assertEqual(result["raw_width"], 70)
        self.assertAlmostEqual(result["width"], 18.0)
        self.assertGreaterEqual(result["width"], 0.30 * result["height"])
        self.assertLessEqual(result["width"], result["raw_width"])

    def test_body_collider_requires_equal_frame_sizes(self) -> None:
        pixels = np.zeros((64, 150, 4), dtype=np.uint8)
        pixels[16:64, 10:30] = [255, 255, 255, 255]
        pixels[16:64, 90:120] = [255, 255, 255, 255]

        image_path = self.temp_dir / "mixed_frames.png"
        Image.fromarray(pixels, mode="RGBA").save(image_path)

        with self.assertRaises(ValueError):
            build_body_collider(
                str(image_path),
                [
                    {"x": 0, "y": 0, "w": 80, "h": 64},
                    {"x": 80, "y": 0, "w": 70, "h": 64},
                ],
            )

    # ------------------------------------------------------------------
    # Full walk-cycle pipeline
    # ------------------------------------------------------------------

    def test_walk_cycle_inspect_build_and_triangle_collision(self) -> None:
        """Build a four-frame walk sheet and exercise the complete pipeline."""

        # Four 32px slots. Each shape uses 31x31 pixels so a one-pixel
        # transparent gutter remains between frames; the 32px slot bounds are
        # still the expected animation frames.
        sheet = _rgba(128, 32)
        draw = ImageDraw.Draw(sheet)
        draw.rectangle([0, 0, 30, 30], fill=(230, 70, 70, 255))
        draw.ellipse([32, 0, 62, 30], fill=(70, 180, 100, 255))
        draw.polygon(
            [(64, 30), (79, 0), (94, 30)],
            fill=(70, 120, 230, 255),
        )
        draw.polygon(
            [(111, 0), (126, 15), (111, 30), (96, 15)],
            fill=(230, 190, 60, 255),
        )

        project = self.temp_dir / "walk_project"
        asset_dir = project / "assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        image_path = asset_dir / "walk.png"
        sheet.save(image_path)

        # 1. Frame inspection.
        layout = inspect_spritesheet(str(image_path))
        self.assertEqual(layout["mode"], "grid")
        self.assertEqual(layout["frame_count"], 4)

        expected_slots = [
            (0, 0, 32, 32),
            (32, 0, 32, 32),
            (64, 0, 32, 32),
            (96, 0, 32, 32),
        ]
        for frame, expected in zip(layout["frames"], expected_slots):
            for key, expected_value in zip(("x", "y", "w", "h"), expected):
                self.assertLessEqual(
                    abs(frame[key] - expected_value),
                    1,
                    msg=f"frame {frame['id']} {key}={frame[key]} "
                    f"deviates from expected {expected_value}",
                )

        # 2. SpriteFrames export.
        animations = [
            {
                "name": "walk",
                "fps": 8.0,
                "loop": True,
                "frames": [
                    {
                        "x": frame["x"],
                        "y": frame["y"],
                        "w": frame["w"],
                        "h": frame["h"],
                    }
                    for frame in layout["frames"]
                ],
            }
        ]
        output_path = project / "resources" / "walk_frames.tres"
        build_result = build_sprite_frames(
            project_root=str(project),
            image_path=str(image_path),
            animations=animations,
            output_tres=str(output_path),
        )

        self.assertTrue(output_path.is_file())
        self.assertEqual(build_result["load_steps"], 6)  # 1 + 4 atlases + 1
        self.assertEqual(build_result["frame_count"], 4)

        tres_text = output_path.read_text(encoding="utf-8")
        self.assertTrue(
            tres_text.startswith(
                '[gd_resource type="SpriteFrames" load_steps=6 format=3]'
            )
        )
        self.assertIn(
            '[ext_resource type="Texture2D" '
            'path="res://assets/walk.png" id="1_tex"]',
            tres_text,
        )
        self.assertIn('"name": &"walk"', tres_text)
        self.assertIn('"loop": true', tres_text)
        self.assertIn('"speed": 8.0', tres_text)
        self.assertEqual(
            tres_text.count('[sub_resource type="AtlasTexture"'), 4
        )
        for frame_index in range(4):
            self.assertIn(
                f'AtlasTexture_walk_{frame_index}', tres_text
            )

        # 3. Collision polygon for the triangle frame.
        triangle = layout["frames"][2]
        collision = extract_collision_polygon(
            str(image_path),
            region={
                "x": triangle["x"],
                "y": triangle["y"],
                "w": triangle["w"],
                "h": triangle["h"],
            },
            epsilon=1.5,
            centered=True,
        )

        self.assertGreaterEqual(collision["vertex_count"], 3)
        self.assertLessEqual(collision["vertex_count"], 6)
        xs = [point[0] for point in collision["points"]]
        ys = [point[1] for point in collision["points"]]
        self.assertTrue(any(value < 0 for value in xs))
        self.assertTrue(any(value > 0 for value in xs))
        self.assertTrue(any(value < 0 for value in ys))
        self.assertTrue(any(value > 0 for value in ys))
        # The triangle fills its slot, so its centred bounding box is
        # symmetric around the origin even though its area is not.
        self.assertAlmostEqual(min(xs) + max(xs), 0.0, delta=1.0)
        self.assertAlmostEqual(min(ys) + max(ys), 0.0, delta=1.0)

        # 4. Test res:// URI support in inspect_spritesheet and build_character_scene
        res_layout = inspect_spritesheet(
            "res://assets/walk.png", project_root=str(project)
        )
        self.assertEqual(res_layout["frame_count"], 4)

        tscn_out = project / "WalkCharacter.tscn"
        scene_res = build_character_scene(
            project_root=str(project),
            image_path="res://assets/walk.png",
            sprite_frames_tres="res://resources/walk_frames.tres",
            output_tscn="res://WalkCharacter.tscn",
            collider_frames=animations[0]["frames"],
            root_name="WalkCharacter",
            default_animation="walk",
        )
        self.assertTrue(tscn_out.is_file())
        self.assertEqual(
            scene_res["sprite_frames_res"], "res://resources/walk_frames.tres"
        )
        tscn_text = tscn_out.read_text(encoding="utf-8")
        self.assertIn('[node name="WalkCharacter" type="CharacterBody2D"]', tscn_text)
        self.assertIn('animation = &"walk"', tscn_text)
        self.assertIn('[node name="CollisionShape2D"', tscn_text)


if __name__ == "__main__":
    unittest.main()
