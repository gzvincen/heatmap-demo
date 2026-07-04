# 病理热力图对比查看器

纯本地运行的病理全切片图像（WSI）对比查看器。将每个病理图的**原图**与**热力图**
自动配对，支持**并排对比**和**叠加**两种查看模式，可无限放大查看细胞细节。

数据全部在本机处理，不上传任何文件。

---

## 快速开始

### 1. 安装依赖

```bash
pip install Pillow
```

> Python 3.8+ 即可运行。

### 2. 启动服务

**macOS / Linux:**
```bash
python3 serve.py
# 或
./serve.sh
```

**Windows:**
```batch
serve.bat
```

默认监听 `http://127.0.0.1:8000/`，可指定端口：

```bash
python3 serve.py 9000        # macOS/Linux
serve.bat 9000               # Windows
```

### 3. 停止服务

**macOS / Linux:**
```bash
./stop.sh
```

**Windows:**
```batch
stop.bat
```

或直接按 `Ctrl+C` 终止服务。

### 4. 打开浏览器

访问 `http://127.0.0.1:8000/`，推荐使用 Chrome 或 Edge。

---

## 使用流程

### 第一步：构建瓦片

在左侧面板输入包含成对图片的**文件夹路径**，然后点击「构建瓦片」。

系统会自动扫描文件夹中的图片，按配对规则匹配原图和热力图，生成 Zoomify 瓦片金字塔。

- 构建过程有**实时进度**显示（当前处理哪个病理图、已处理/总数、预计剩余时间）
- 已存在的瓦片会自动跳过（勾选「强制重建」可重新生成）
- 瓦片输出到源文件夹下的 `tiles/` 子目录

### 第二步：选择病理图

构建完成后，从下拉列表中选择要查看的病理图。

### 第三步：查看对比

点击顶部模式按钮切换：

| 模式 | 说明 |
|------|------|
| **并排对比** | 原图和热力图左右并排显示，中间有分隔线 |
| **叠加** | 热力图叠加在原图上，可调节不透明度 |

### 放大与导航

- **鼠标滚轮**：缩放
- **鼠标拖动**：平移
- **放大倍数**：最高 40 倍，可查看细胞细节
- 工具栏按钮：放大 / 缩小 / 适应窗口 / 旋转 / 全屏

---

## 文件配对规则

系统支持两种配对模式，在侧边栏「配对规则」区域配置：

### 分隔符模式（默认）

按文件名中的分隔符（默认 `_`）拆分，自动识别原图和热力图：

- **原图关键词**：`orig`、`original`、`HE`、`hne`、`source`、`raw`
- **热力图关键词**：`heat`、`heatmap`、`overlay`、`AI`、`SBST`、`mask`、`pred` 等

示例：
```
C3L-00011-21_orig.jpg     → 原图（含 orig 关键词）
C3L-00011-21_heat.jpg     → 热力图（含 heat 关键词）
C3L-00011-21_HE.jpg       → 原图（含 HE 关键词）
C3L-00011-21_AI.jpg       → 热力图（含 AI 关键词）
```

可自定义：
- **分隔符**：修改「分隔符」输入框（如改为 `-`）
- **原图关键词**：修改「原图关键词」输入框，逗号分隔

### 正则模式

用正则表达式精确匹配：

- 捕获组 1 = 病理图编号（前缀）
- 捕获组 2（可选）= 角色标识，含 `orig`/`HE` 等 → 原图，否则 → 热力图

示例：
```
正则：^(.+?)_(orig|heat)$
C3L-00011-21_orig.jpg → 前缀=C3L-00011-21, 角色=orig
C3L-00011-21_heat.jpg → 前缀=C3L-00011-21, 角色=heat
```

---

## 项目结构

```
heatmap-demo/
├── serve.py                 # 本地服务器（静态文件 + API）
── serve.sh                 # 启动脚本（macOS/Linux）
├── serve.bat                # 启动脚本（Windows）
├── stop.sh                  # 停止脚本（macOS/Linux）
├── stop.bat                 # 停止脚本（Windows）
├── tile_folder.py           # 瓦片生成工具
├── README.md                # 本文件
└── site/
    ├── index.html           # 主页面
    ├── local.js             # 前端逻辑
    ├── viewer-frame.html    # Zoomify iframe 查看器
    ├── ZoomifyImageViewerPro-min.js  # Zoomify 库
    └── Assets/Skins/        # 工具栏皮肤
```

构建瓦片后，源文件夹下会生成：
```
<源文件夹>/
├── *.jpg                    # 原始图片
└── tiles/                   # 瓦片输出目录
    ├── manifest.json        # 病理图清单
    ├── <case>/
    │   ├── orig/            # 原图瓦片
    │   │   ├── ImageProperties.xml
    │   │   └── TileGroupN/z-x-y.jpg
    │   ├── heat/            # 热力图瓦片
    │   ├── comparison.xml   # 并排对比配置
    │   └── overlay.xml      # 叠加配置
    └── ...
```

---

## 命令行直接使用

也可以不启动 Web 服务，直接用命令行生成瓦片：

```bash
# macOS/Linux
python3 tile_folder.py "/path/to/images" [选项]

# Windows
python tile_folder.py "C:\path\to\images" [选项]
```

常用选项：

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--out DIR` | 瓦片输出目录 | `<源文件夹>/tiles/` |
| `--quality N` | JPEG 质量 (1-100) | 85 |
| `--force` | 强制重新生成（忽略已有瓦片） | false |
| `--pair-mode MODE` | 配对模式：`delim` 或 `regex` | delim |
| `--pair-delim DELIM` | 分隔符模式的分隔符 | `_` |
| `--pair-keywords KW` | 原图角色关键词，逗号分隔 | orig,original,HE |
| `--pair-regex PATTERN` | 正则模式的表达式 | - |

示例：
```bash
# 基本用法
python3 tile_folder.py "/path/to/images"

# 指定输出目录和质量
python3 tile_folder.py "/path/to/images" --out /tmp/tiles --quality 90

# 使用正则模式
python3 tile_folder.py "/path/to/images" --pair-mode regex --pair-regex "^(.+?)_(orig|heat)"

# 强制重建所有瓦片
python3 tile_folder.py "/path/to/images" --force
```

---

## API 接口

服务启动后提供以下 API：

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/case-list` | GET | 获取可用病理图列表 |
| `/api/tile-status` | GET | 获取当前构建进度 |
| `/api/select-folder` | GET | 打开本机文件夹选择框并返回路径 |
| `/api/build-tiles` | POST | 触发瓦片构建 |
| `/tiles/...` | GET | 访问瓦片文件 |

### 触发构建

```bash
curl -X POST http://127.0.0.1:8000/api/build-tiles \
  -H "Content-Type: application/json" \
  -d '{
    "folder": "/path/to/images",
    "pairMode": "delim",
    "pairDelim": "_",
    "force": false
  }'
```

### 查询进度

```bash
curl http://127.0.0.1:8000/api/tile-status
```

返回示例：
```json
{
  "status": "processing",
  "total": 40,
  "current": 15,
  "case": "C3L-00011-21",
  "role": "orig",
  "tiles": 1024,
  "percent": 37.5
}
```

---

## 常见问题

### Q: 构建很慢怎么办？

- 病理图通常很大（100MB+），首次构建需要切分成数千个瓦片，耗时较长
- 后续构建会自动跳过已存在的瓦片，速度很快
- 可勾选「强制重建」来重新生成（不推荐频繁使用）

### Q: 放大后图片模糊？

- 瓦片是基于原始图片分辨率生成的，放大到极限后自然会模糊
- 这是正常现象，原始图片的分辨率决定了最大清晰度
- 最大放大倍数为 40 倍，足以查看细胞细节

### Q: 下拉列表没有刷新？

- 构建完成后，下拉列表会自动更新
- 如果构建过程中列表被禁用，请等待构建完成

### Q: 瓦片可以删除吗？

- 可以删除源文件夹下的 `tiles/` 目录
- 删除后需要重新构建瓦片才能查看

---

## 技术细节

- **Zoomify 瓦片金字塔**：将大图切分为多层级的 256x256 瓦片，支持渐进式加载
- **iframe 隔离**：每个查看器实例在独立 iframe 中运行，避免状态冲突
- **实时进度**：通过 `.build-progress.json` 文件轮询实现构建进度展示
- **配对规则**：灵活的文件名解析，支持分隔符和正则两种模式
