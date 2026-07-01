#!/usr/bin/env python3
"""把一个本地文件夹里成对的病理图（原图 + 热力图）切成 Zoomify 瓦片金字塔，
输出到 site/tiles/，供原始 Zoomify 查看器直接按 URL 访问。

配对规则（两种模式，默认分隔符模式）：
  模式 A — 分隔符模式（--pair-mode delim）：
    - 按分隔符（默认 _）拆分文件名
    - 从各段中识别"角色关键词"（orig/original/HE/heatmap/heat/overlay/AI/SBST 等）
    - 去掉角色段后剩余部分拼接为前缀（即病理图编号）
    - 含 orig/original/HE 关键词的判定为原图，其余为热力图
  模式 B — 正则模式（--pair-mode regex --pair-regex PATTERN）：
    - 正则捕获组 1 = 前缀
    - 正则捕获组 2 = 角色标识（可选，用于判定原图/热力图）

每个病理图生成：
  site/tiles/<case>/orig/  (ImageProperties.xml + TileGroupN/z-x-y.jpg)
  site/tiles/<case>/heat/
  site/tiles/<case>/comparison.xml   (并排对比)
  site/tiles/<case>/overlay.xml      (叠加)
并汇总 site/tiles/manifest.json（病理图列表）。

进度输出：
  运行时写入 <out>/.build-progress.json，前端可轮询获取实时进度。

用法：
  python3 tile_folder.py "/path/to/folder"
  python3 tile_folder.py "/path/to/folder" --pair-mode delim --pair-delim _ --pair-keywords orig,original,HE,heatmap
  python3 tile_folder.py "/path/to/folder" --pair-mode regex --pair-regex "^(.+?)_(?:orig|heat)"
  python3 tile_folder.py "/path/to/folder" --quality 85 --out site/tiles --force
"""
import argparse
import json
import math
import os
import re
import sys
import tempfile

from PIL import Image

Image.MAX_IMAGE_PIXELS = None  # 病理图较大，关闭 DecompressionBomb 限制
TILE = 256
IMG_RE = re.compile(r"\.(jpe?g|png|webp|bmp|tiff?)$", re.I)

# 原图角色关键词（命中即判定为原图）
DEFAULT_ORIG_KEYWORDS = {"orig", "original", "he", "h&e", "hne", "source", "raw"}
# 热力图角色关键词（仅用于辅助判定，未命中原图关键词的默认归为热力图）
DEFAULT_HEAT_KEYWORDS = {"heat", "heatmap", "overlay", "ai", "sbst", "mask", "pred", "prediction"}

MAX_ZOOM = 400000  # 最大放大倍数（百分比）。Zoomify 会将>1 的值除以 100 转为倍率，但存在双重转换 bug，需要设置极大值

PROGRESS_FILE = ".build-progress.json"


# ─── 配对规则 ───────────────────────────────────────────────────────────────

def _base_name(filename):
    """去掉扩展名。"""
    return os.path.splitext(filename)[0]


def make_delim_parser(delim="_", keywords=None):
    """返回 (prefix_fn, role_fn) 两个函数，用于分隔符模式。

    prefix_fn(filename) -> str | None   提取前缀，失败返回 None
    role_fn(filename)    -> "orig" | "heat" | None
    """
    orig_kw = DEFAULT_ORIG_KEYWORDS
    if keywords:
        # 用户指定的关键词全部视为原图关键词
        orig_kw = {k.strip().lower() for k in keywords.split(",")}

    def prefix_fn(filename):
        name = _base_name(filename)
        parts = name.split(delim)
        # 找到第一个角色关键词的位置，取其之前的所有段作为前缀
        for idx, p in enumerate(parts):
            if p.lower() in orig_kw or p.lower() in DEFAULT_HEAT_KEYWORDS:
                return delim.join(parts[:idx]) if idx > 0 else None
        # 没找到角色关键词：取第一段 + 后续非参数段（参数段以数字开头或是 roi/blur/rs 等）
        PARAM_KEYWORDS = {"roi", "blur", "rs", "bc", "bi", "l", "a"}
        prefix_parts = [parts[0]] if parts else []
        for p in parts[1:]:
            if p[0].isdigit() or p.lower() in PARAM_KEYWORDS:
                break
            prefix_parts.append(p)
        return delim.join(prefix_parts) if len(prefix_parts) > 1 else (prefix_parts[0] if prefix_parts else None)

    def role_fn(filename):
        name = _base_name(filename).lower()
        parts = [p.lower() for p in name.split(delim)]
        for p in parts:
            if p in orig_kw:
                return "orig"
        return "heat"

    return prefix_fn, role_fn


def make_regex_parser(pattern):
    """返回 (prefix_fn, role_fn) 两个函数，用于正则模式。

    正则要求：
      捕获组 1 = 前缀（病理图编号）
      捕获组 2（可选）= 角色标识，含 orig/original/HE 等 → 原图，否则 → 热力图
    """
    compiled = re.compile(pattern)

    def prefix_fn(filename):
        m = compiled.search(_base_name(filename))
        return m.group(1) if m and m.group(1) else None

    def role_fn(filename):
        m = compiled.search(_base_name(filename))
        if not m:
            return "heat"
        if m.lastindex and m.lastindex >= 2 and m.group(2):
            tag = m.group(2).lower()
            if tag in DEFAULT_ORIG_KEYWORDS or tag in ("he", "h&e", "hne", "source", "raw"):
                return "orig"
        return "heat"

    return prefix_fn, role_fn


# ─── 进度输出 ────────────────────────────────────────────────────────────────

def write_progress(out_dir, total, current, case, role, tiles, status="processing"):
    """写入进度 JSON 到 out_dir/.build-progress.json。"""
    data = {
        "total": total,
        "current": current,
        "case": case or "",
        "role": role or "",
        "tiles": tiles,
        "status": status,  # processing | done | error
        "percent": round(current / total * 100, 1) if total else 0,
    }
    path = os.path.join(out_dir, PROGRESS_FILE)
    with open(path, "w") as f:
        json.dump(data, f)


def clear_progress(out_dir):
    path = os.path.join(out_dir, PROGRESS_FILE)
    if os.path.exists(path):
        os.remove(path)


# ─── 瓦片生成 ────────────────────────────────────────────────────────────────

def tier_dims(w, h):
    """tier 0 = 最小（单瓦片），最后一个 = 全分辨率。"""
    dims = [(w, h)]
    while w > TILE or h > TILE:
        w = math.ceil(w / 2)
        h = math.ceil(h / 2)
        dims.append((w, h))
    dims.reverse()
    return dims


def write_zoomify(src_path, out_dir, quality):
    img = Image.open(src_path)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    W, H = img.size
    dims = tier_dims(W, H)
    index = 0
    for tier, (tw, th) in enumerate(dims):
        timg = img if (tw, th) == (W, H) else img.resize((tw, th), Image.LANCZOS)
        cols = math.ceil(tw / TILE)
        rows = math.ceil(th / TILE)
        for row in range(rows):
            for col in range(cols):
                gdir = os.path.join(out_dir, "TileGroup%d" % (index // 256))
                os.makedirs(gdir, exist_ok=True)
                box = (col * TILE, row * TILE,
                       min((col + 1) * TILE, tw), min((row + 1) * TILE, th))
                timg.crop(box).save(
                    os.path.join(gdir, "%d-%d-%d.jpg" % (tier, col, row)),
                    "JPEG", quality=quality)
                index += 1
    with open(os.path.join(out_dir, "ImageProperties.xml"), "w") as f:
        f.write('<IMAGE_PROPERTIES WIDTH="%d" HEIGHT="%d" NUMTILES="%d" '
                'NUMIMAGES="1" VERSION="1.8" TILESIZE="%d" />' % (W, H, index, TILE))
    return index


def write_manifests(case_dir, rel):
    """生成 Zoomify 并排对比 / 叠加 的 XML 清单。"""
    with open(os.path.join(case_dir, "comparison.xml"), "w") as f:
        f.write(
            '<COMPARISONDATA>\n<SETUP SYNCVISIBLE="1" INITIALSYNC="1"></SETUP>\n'
            '<IMAGE MEDIA="%s/orig" NAME="原图" INITIALZOOM="-1" MINZOOM="-1" MAXZOOM="%d"></IMAGE>\n'
            '<IMAGE MEDIA="%s/heat" NAME="热力图" INITIALZOOM="-1" MINZOOM="-1" MAXZOOM="%d"></IMAGE>\n'
            '</COMPARISONDATA>\n' % (rel, MAX_ZOOM, rel, MAX_ZOOM))
    with open(os.path.join(case_dir, "overlay.xml"), "w") as f:
        f.write(
            '<OVERLAYDATA>\n<SETUP CHOICELIST="0"></SETUP>\n'
            '<OVERLAY MEDIA="%s/heat" NAME="热力图"></OVERLAY>\n'
            '</OVERLAYDATA>\n' % rel)


# ─── 主流程 ──────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="病理图 → Zoomify 瓦片")
    ap.add_argument("folder", help="包含成对图片的本地文件夹")
    ap.add_argument("--out", default=None, help="瓦片输出目录 (默认 <folder>/tiles/)")
    ap.add_argument("--quality", type=int, default=85, help="JPEG 质量 (默认 85)")
    ap.add_argument("--force", action="store_true", help="即使已存在也重切")

    # 配对规则
    ap.add_argument("--pair-mode", choices=["delim", "regex"], default="delim",
                    help="配对模式: delim=分隔符模式(默认), regex=正则模式")
    ap.add_argument("--pair-delim", default="_",
                    help="分隔符模式的分隔符 (默认 _)")
    ap.add_argument("--pair-keywords", default=None,
                    help="分隔符模式的原图角色关键词，逗号分隔 (默认: orig,original,HE)")
    ap.add_argument("--pair-regex", default=None,
                    help="正则模式的正则表达式 (捕获组1=前缀, 捕获组2=角色标识)")
    args = ap.parse_args()

    if not os.path.isdir(args.folder):
        sys.exit("文件夹不存在: " + args.folder)

    # 默认输出到源文件夹的 tiles/ 子目录
    if args.out is None:
        args.out = os.path.join(args.folder, "tiles")

    # 初始化配对解析器
    if args.pair_mode == "regex":
        if not args.pair_regex:
            sys.exit("正则模式必须指定 --pair-regex")
        try:
            re.compile(args.pair_regex)
        except re.error as e:
            sys.exit("正则表达式无效: %s" % e)
        prefix_fn, role_fn = make_regex_parser(args.pair_regex)
    else:
        prefix_fn, role_fn = make_delim_parser(args.pair_delim, args.pair_keywords)

    # 扫描文件并按前缀分组
    files = [f for f in os.listdir(args.folder) if IMG_RE.search(f)]
    cases = {}
    unmatched = []
    for f in files:
        prefix = prefix_fn(f)
        if not prefix:
            unmatched.append(f)
            continue
        role = role_fn(f)
        cases.setdefault(prefix, {})[role] = f

    if unmatched:
        print(" 以下文件未能匹配配对规则，已跳过:")
        for f in unmatched:
            print("   - %s" % f)

    keys = sorted(cases)
    if not keys:
        sys.exit("未找到可配对的图片，请检查 --pair-mode / --pair-regex 配置")

    print("找到 %d 个病理图，共 %d 个文件" % (len(keys), len(files)))

    os.makedirs(args.out, exist_ok=True)
    # 瓦片通过 serve.py 的 /tiles/ 路由服务，web 路径固定为 tiles/
    web_prefix = "tiles"
    manifest = []
    total_steps = len(keys) * 2  # 每个 case 有 orig + heat 两步

    for i, k in enumerate(keys, 1):
        c = cases[k]
        rel = "%s/%s" % (web_prefix, k)
        case_dir = os.path.join(args.out, k)
        entry = {"case": k, "orig": bool(c.get("orig")), "heat": bool(c.get("heat"))}

        for role_idx, role in enumerate(("orig", "heat")):
            step_num = (i - 1) * 2 + role_idx + 1
            if role not in c:
                write_progress(args.out, total_steps, step_num - 1, k, role, 0, "skip")
                continue

            sub = os.path.join(case_dir, role)
            if os.path.exists(os.path.join(sub, "ImageProperties.xml")) and not args.force:
                write_progress(args.out, total_steps, step_num, k, role, 0, "skip")
                print("[%d/%d] %s/%s 已存在，跳过" % (i, len(keys), k, role))
                continue

            os.makedirs(sub, exist_ok=True)
            write_progress(args.out, total_steps, step_num - 1, k, role, 0, "processing")
            n = write_zoomify(os.path.join(args.folder, c[role]), sub, args.quality)
            write_progress(args.out, total_steps, step_num, k, role, n, "done")
            print("[%d/%d] %s/%s -> %d 瓦片" % (i, len(keys), k, role, n))

        if c.get("orig") and c.get("heat"):
            write_manifests(case_dir, rel)
        manifest.append(entry)

    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    write_progress(args.out, total_steps, total_steps, "", "", 0, "done")
    print("完成：%d 个病理图 -> %s/manifest.json" % (len(manifest), args.out))


if __name__ == "__main__":
    main()
