# godot-sprite-mcp

[![CI](https://github.com/huha007/godot-sprite-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/huha007/godot-sprite-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](pyproject.toml)

**[English](README.md) | [简体中文](README_zh.md)**

一个专为 **Godot 4.x** 打造的轻量级 **MCP (Model Context Protocol) 工具服务与命令行工具**。
无需打开 Godot 编辑器、无需安装笨重的 OpenCV，直接从 PNG 精灵图的 Alpha 透明通道自动识别切帧、导出 Godot 4 `SpriteFrames (.tres)` 动画资源、计算**脚底对齐且自动滤除长柄武器**的角色身体碰撞框（`CollisionShape2D`），并支持一键生成完整的 `.tscn` 角色场景文件。

![动态演示](docs/demo_animation.gif)

![碰撞框算法对比](docs/showcase_collider.png)

> *如上图所示：即便在挥舞长剑的攻击序列帧（原始像素宽度达 `128px`）下，**30% 竖向厚度过滤算法**依然能自动削掉伸出的 74px 细薄剑刃，保留稳定的 `54×112px` 躯干碰撞框；同时对扁宽的史莱姆则自动保留 `99×112px` 的宽身体框。*

## ✨ 核心功能

| MCP 工具名 | 功能说明 |
| :--- | :--- |
| **`inspect_spritesheet`** | 分析 PNG 透明通道，自动识别规则网格（Grid）或不规则排布的独立精灵帧（Islands）坐标（原生支持 `res://` 路径）。 |
| **`build_sprite_frames`** | 根据切帧结果，直接生成符合 Godot 4 (`format=3`) 规范的 `SpriteFrames` `.tres` 动画资源文件。 |
| **`build_body_collider`** | 叠加动画序列帧并通过 **30% 竖向厚度过滤算法**，生成脚底对齐 `(0, 0)` 原点的稳定 `RectangleShape2D` / `CapsuleShape2D` 碰撞数据。 |
| **`build_character_scene`** | 一步到位生成完整的 Godot 4 `.tscn` 角色场景文件（自动组装 `CharacterBody2D` + `AnimatedSprite2D` + 脚底对齐 `CollisionShape2D`）。 |
| **`extract_collision_polygon`** | 提取像素外轮廓并进行多边形抽稀简化（<= 24 顶点），为石头、箱子等静态物体生成 `CollisionPolygon2D`。 |

---

## 🚀 快速开始（MCP 配置）

**前置环境要求：** Python 3.10+、Git 以及 [`uv`](https://docs.astral.sh/uv/)（若使用 `uvx` 方式）。

将 `godot-sprite-mcp` 添加到你的 AI 编程客户端（如 **Cursor、Claude Code、Windsurf、Cline、Claude Desktop** 等）的 `mcp.json` 配置文件中：

### 方式一：通过 `uvx` 免安装运行

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

### 方式二：克隆到本地 / Conda 环境运行

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
*(若在 Windows 下使用未加入全局 `PATH` 的虚拟环境或 Conda 环境，可将 `"command"` 填为对应环境的 `python.exe` 绝对路径，`"args"` 填为 `["-m", "godot_sprite_mcp"]`。)*

---

## 💬 提问示例

配置完成后，直接在聊天框用自然语言让 AI 处理你的精灵图：

- *“帮我分析项目 `D:/my_game` 下的 `res://assets/knight_sheet.png`，把第一行做成 `idle`、第二行做成 `run`、第三行做成 `attack` 导出到 `res://resources/knight_frames.tres`，并调用 `build_character_scene` 直接生成 `res://Knight.tscn` 角色场景。”*
- *“读取 `res://assets/slime.png`，给这只史莱姆生成动画资源和脚底对齐的 `Slime.tscn` 场景。”*

---

## 🛠️ 命令行独立使用（CLI 模式）

```bash
# 1. 自动识别精灵图切帧坐标
godot-sprite-mcp inspect assets/knight_sheet.png --mode auto

# 2. 生成 Godot 4 SpriteFrames (.tres) 动画资源
godot-sprite-mcp build \
  --project-root . \
  --image assets/knight_sheet.png \
  --animations @animations.json \
  --output res://resources/knight_frames.tres

# 3. 计算脚底对齐的稳定角色身体碰撞框
godot-sprite-mcp body-collision assets/knight_sheet.png \
  --frames @idle_frames.json \
  --shape rectangle \
  --thickness-ratio 0.30

# 4. 为静态障碍物提取紧贴轮廓的多边形碰撞
godot-sprite-mcp collision assets/rock.png --epsilon 2.0
```

## ⚠️ 适用范围与局限性（Limitations）

- **依赖 PNG Alpha 透明通道**：切帧与轮廓/碰撞计算均基于透明背景（`alpha <= alpha_threshold`），纯色不透明背景的素材需先转为透明底 PNG。
- **网格模式与孤岛模式**：`mode="grid"` 要求行列之间存在全透明分割间隔且单格尺寸一致；若帧尺寸不一，`mode="auto"` 会自动回退至 8 连通域 `islands` 模式。
- **物理移动框 vs. 逐帧战斗判定框**：`build_body_collider` 旨在为移动角色生成单一稳定的物理躯干框（`CharacterBody2D`），而非动作游戏中随每帧刀光变化的近战攻击判定框（`Area2D` Hitbox）。

## 🧪 运行单元测试

```bash
pip install -e ".[dev]"
pytest -v
```

## 📄 开源协议

[MIT](LICENSE)
