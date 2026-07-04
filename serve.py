#!/usr/bin/env python3
"""病理热力图查看器本地服务器。

提供静态文件服务 + API：
  GET  /api/tile-status    返回当前瓦片构建进度
  GET  /api/case-list      返回可用病理图列表
  GET  /api/select-folder  打开本机文件夹选择框并返回路径
  POST /api/build-tiles    触发瓦片构建
  GET  /tiles/...          服务瓦片文件（从配置的 tiles 目录）

瓦片目录通过配置文件 .tile-config.json 记录（构建时自动写入）。
PID 文件 .serve.pid 用于停止脚本定位进程。

Usage: python3 serve.py [port]   (default 8000)
"""
import json
import os
import platform
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PROJECT_ROOT, ".tile-config.json")
PID_FILE = os.path.join(PROJECT_ROOT, ".serve.pid")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

_build_lock = threading.Lock()
_build_proc = None
_current_build_tiles_dir = None  # 当前构建的瓦片目录（构建期间使用）


def _json_response(handler, data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _load_config():
    """读取 tiles 目录配置。"""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    # 默认回退到 site/tiles
    return {"tiles_dir": os.path.join(ROOT, "tiles")}


def _save_config(tiles_dir):
    """保存 tiles 目录配置。"""
    with open(CONFIG_PATH, "w") as f:
        json.dump({"tiles_dir": tiles_dir}, f)


def _get_tiles_dir():
    return _load_config().get("tiles_dir", os.path.join(ROOT, "tiles"))


def _read_progress():
    # 构建期间使用当前构建的目录，否则使用配置中的目录
    tiles_dir = _current_build_tiles_dir or _get_tiles_dir()
    path = os.path.join(tiles_dir, ".build-progress.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def _select_folder():
    """打开本机目录选择框，返回用户选择的真实路径。"""
    system = platform.system()

    if system == "Darwin":
        script = 'POSIX path of (choose folder with prompt "选择病理图文件夹")'
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None, "已取消选择" if result.returncode == 1 else result.stderr.strip()
        return result.stdout.strip(), None

    if system == "Windows":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$d.Description = '选择病理图文件夹'; "
            "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None, result.stderr.strip() or "文件夹选择器启动失败"
        folder = result.stdout.strip()
        return (folder, None) if folder else (None, "已取消选择")

    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory(title="选择病理图文件夹")
        root.destroy()
        return (folder, None) if folder else (None, "已取消选择")
    except Exception as exc:
        return None, "当前环境无法打开文件夹选择器: %s" % exc


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def guess_type(self, path):
        ctype = super().guess_type(path)
        if ctype.startswith("text/") or "javascript" in ctype:
            if "charset=" not in ctype:
                ctype += "; charset=utf-8"
        return ctype

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/tile-status":
            self._handle_tile_status()
        elif path == "/api/case-list":
            self._handle_case_list()
        elif path == "/api/select-folder":
            self._handle_select_folder()
        elif path.startswith("/tiles/"):
            self._serve_tile(path)
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/build-tiles":
            self._handle_build_tiles()
        else:
            self.send_error(404)

    def _handle_tile_status(self):
        progress = _read_progress()
        _json_response(self, progress)

    def _handle_case_list(self):
        tiles_dir = _get_tiles_dir()
        manifest_path = os.path.join(tiles_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            _json_response(self, {"cases": [], "total": 0})
            return
        with open(manifest_path, "r") as f:
            cases = json.load(f)
        _json_response(self, {"cases": cases, "total": len(cases)})

    def _handle_select_folder(self):
        folder, error = _select_folder()
        if error:
            _json_response(self, {"error": error}, 400)
            return
        if not folder or not os.path.isdir(folder):
            _json_response(self, {"error": "文件夹路径无效"}, 400)
            return
        _json_response(self, {"folder": folder})

    def _serve_tile(self, path):
        """服务 /tiles/... 请求，从配置的 tiles 目录读取文件。"""
        tiles_dir = _get_tiles_dir()
        # 去掉 /tiles/ 前缀，得到相对路径
        rel_path = path[len("/tiles/"):]
        # 安全检查：防止路径穿越
        rel_path = os.path.normpath(rel_path)
        if rel_path.startswith("..") or rel_path.startswith("/"):
            self.send_error(403)
            return

        file_path = os.path.join(tiles_dir, rel_path)
        if not os.path.isfile(file_path):
            self.send_error(404)
            return

        # 确定 MIME 类型
        ctype = self.guess_type(file_path)
        with open(file_path, "rb") as f:
            content = f.read()

        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(content)

    def _handle_build_tiles(self):
        global _build_proc
        with _build_lock:
            if _build_proc is not None and _build_proc.poll() is None:
                _json_response(self, {"error": "构建正在进行中"}, 409)
                return

            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            try:
                params = json.loads(body) if body else {}
            except json.JSONDecodeError:
                _json_response(self, {"error": "无效的 JSON"}, 400)
                return

            folder = params.get("folder", "").strip()
            if not folder or not os.path.isdir(folder):
                _json_response(self, {"error": "文件夹路径无效: %s" % folder}, 400)
                return

            # 瓦片输出到源文件夹的 tiles/ 子目录
            tiles_dir = os.path.join(folder, "tiles")

            pair_mode = params.get("pairMode", "delim")
            pair_delim = params.get("pairDelim", "_")
            pair_keywords = params.get("pairKeywords", None)
            pair_regex = params.get("pairRegex", None)
            force = params.get("force", False)

            cmd = [
                sys.executable,
                os.path.join(PROJECT_ROOT, "tile_folder.py"),
                folder,
                "--out", tiles_dir,
                "--pair-mode", pair_mode,
                "--pair-delim", pair_delim,
            ]
            if pair_keywords:
                cmd.extend(["--pair-keywords", pair_keywords])
            if pair_regex:
                cmd.extend(["--pair-regex", pair_regex])
            if force:
                cmd.append("--force")

            # 同步写入初始进度（在发送响应之前，防止竞态条件）
            os.makedirs(tiles_dir, exist_ok=True)
            try:
                with open(os.path.join(tiles_dir, ".build-progress.json"), "w") as f:
                    json.dump({"status": "starting", "percent": 0, "total": 0, "current": 0, "case": "", "role": "", "tiles": 0}, f)
            except Exception:
                pass

            def _run_build():
                global _build_proc, _current_build_tiles_dir
                _current_build_tiles_dir = tiles_dir  # 设置当前构建目录
                try:
                    _build_proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        cwd=PROJECT_ROOT,
                    )
                    _build_proc.wait()
                    # 构建完成后保存配置
                    _save_config(tiles_dir)
                finally:
                    _build_proc = None
                    _current_build_tiles_dir = None  # 清除构建目录

            threading.Thread(target=_run_build, daemon=True).start()
            _json_response(self, {"status": "started", "tiles_dir": tiles_dir})


if __name__ == "__main__":
    if not os.path.isfile(os.path.join(ROOT, "index.html")):
        sys.exit("site/index.html not found")

    # 写入 PID 文件，供停止脚本使用
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"病理热力图查看器: http://127.0.0.1:{PORT}/")
    print(f"  静态文件：{ROOT}")
    print(f"  瓦片目录：{_get_tiles_dir()}")
    print(f"  PID: {os.getpid()}")
    print("按 Ctrl+C 停止服务，或运行 ./stop.sh (Windows: stop.bat)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
