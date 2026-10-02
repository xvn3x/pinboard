"""Pinboard: a local, authenticated UI around the existing downloader."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import app

FROZEN = getattr(sys, "frozen", False)
ROOT = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent
ASSETS = Path(getattr(sys, "_MEIPASS", ROOT)) / "web"
ACTIVE = {"starting", "downloading", "packing", "stopping"}


class Library:
    def __init__(self, home: Path):
        self.home = home
        self.config = home / ".pinboard" / "settings.json"
        settings = app.read_json(self.config) or {}
        self.output = Path(settings.get("output", str(home / "downloads"))).expanduser().resolve()
        self.lock = threading.RLock()
        self.job = None
        self.process = None
        self.cancelled = threading.Event()

    def set_output(self, raw):
        if not isinstance(raw, str) or not raw.strip():
            raise app.AppError("Введите путь к папке.")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            raise app.AppError("Укажите полный путь, например D:\\Pinterest.")
        with self.lock:
            if self.job and self.job["status"] in ACTIVE:
                raise app.AppError("Дождитесь завершения загрузки перед сменой папки.")
            path.mkdir(parents=True, exist_ok=True)
            self.config.parent.mkdir(parents=True, exist_ok=True)
            app.write_json_atomic(self.config, {"output": str(path.resolve())})
            self.output = path.resolve()

    def board_path(self, name):
        if not name or Path(name).name != name or name in {".", ".."}:
            raise app.AppError("Доска не найдена.")
        target = (self.output / name).resolve()
        if target.parent != self.output or not target.is_dir():
            raise app.AppError("Доска не найдена.")
        return target

    def boards(self):
        result = []
        if not self.output.exists():
            return result
        for directory in self.output.iterdir():
            if not directory.is_dir() or directory.name.startswith(".") or directory.is_symlink():
                continue
            files = sorted((p for p in directory.iterdir() if p.is_file() and not p.is_symlink()
                            and p.suffix.lower() in app.MEDIA_EXTENSIONS), key=lambda p: p.name)
            if not files:
                continue
            manifest = app.read_json(directory / "manifest.json") or {}
            board = manifest.get("board") or {}
            pieces = directory.name.split("__", 1)
            name = board.get("name") or pieces[-1].replace("-", " ")
            owner = board.get("username") or (pieces[0] if len(pieces) == 2 else "Pinterest")
            kind = manifest.get("source_type") or ("pin" if directory.name.startswith("pin__") else "board")
            if kind == "pin":
                name = next((item.get("title") for item in manifest.get("items", []) if item.get("title")), None) or f"Пин {pieces[-1]}"
                owner = board.get("username") or "Pinterest"
            result.append({"id": directory.name, "name": name, "owner": owner,
                           "source_type": kind,
                           "count": len(files), "bytes": sum(p.stat().st_size for p in files),
                           "covers": [p.name for p in files if p.suffix.lower() in app.IMAGE_EXTENSIONS][:3],
                           "updated": (directory / "manifest.json").stat().st_mtime if manifest else directory.stat().st_mtime,
                           "url": manifest.get("board_url", ""),
                           "zip": (self.output / (directory.name + ".zip")).is_file(),
                           "status": manifest.get("status", "imported")})
        return sorted(result, key=lambda b: b["updated"], reverse=True)

    def state(self):
        with self.lock:
            return {"version": app.APP_VERSION, "output": str(self.output),
                    "job": dict(self.job) if self.job else None, "boards": self.boards()}

    def start(self, data):
        raw = data.get("url", "")
        if not isinstance(raw, str) or len(raw) > 4096:
            raise app.AppError("Проверьте ссылку на доску или пин.")
        limit = data.get("limit")
        if limit is not None and (type(limit) is not int or not 1 <= limit <= 100000):
            raise app.AppError("Лимит должен быть числом от 1 до 100 000.")
        browser = data.get("browser") or None
        if browser not in {None, "chrome", "edge", "firefox"}:
            raise app.AppError("Выберите браузер из списка.")
        # Validate ordinary URLs synchronously; short links resolve in the worker.
        if (urlsplit(raw if "://" in raw else "https://" + raw).hostname or "").lower() != "pin.it":
            app.parse_pinterest_url(raw)
        with self.lock:
            if self.job and self.job["status"] in ACTIVE:
                raise app.AppError("Уже идёт загрузка. Дождитесь её завершения или остановите её.")
            self.cancelled.clear()
            self.job = {"status": "starting", "url": raw, "name": "Подключаемся к Pinterest",
                        "count": 0, "bytes": 0, "lines": [], "started": time.time(), "message": "Проверяем ссылку…"}
            threading.Thread(target=self.download, args=(raw, limit, browser, bool(data.get("zip", True))), daemon=True).start()

    def update(self, **kwargs):
        with self.lock:
            self.job.update(kwargs)

    def stop(self):
        with self.lock:
            if self.job and self.job["status"] in {"starting", "downloading"}:
                self.cancelled.set()
                self.job.update(status="stopping", message="Останавливаем загрузку…")

    def download(self, raw, limit, browser, make_zip):
        try:
            url, name = app.parse_pinterest_url(raw)
            if app.source_kind(url) != "board":
                limit = None
            if self.cancelled.is_set():
                self.update(status="cancelled", message="Загрузка остановлена.")
                return
            board = self.output / name
            if board.resolve().parent != self.output:
                raise app.AppError("Папка доски находится за пределами папки загрузок.")
            state = board / ".pbd"
            state.mkdir(parents=True, exist_ok=True)
            log = board / "download.log"
            command = app.build_gallery_command(url, board, state, log, limit, browser)[3:]
            launcher = [sys.executable] if FROZEN else [sys.executable, str(Path(__file__).resolve())]
            command = launcher + ["--gallery-worker", str(log)] + command
            title = f"Пин {name.split('__')[-1]}" if app.source_kind(url) == "pin" else name.split("__")[-1].replace("-", " ")
            self.update(status="downloading", name=title, board_id=name,
                        message="Скачивание файлов…")
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.process = process
            while process.poll() is None:
                if self.cancelled.is_set():
                    process.terminate()
                    process.wait(timeout=10)
                    break
                self.progress(board, log)
                time.sleep(.6)
            self.progress(board, log)
            app.move_metadata(board, state / "metadata")
            manifest = app.build_manifest(url, board, state / "metadata", log, process.returncode, limit)
            app.write_json_atomic(board / "manifest.json", manifest)
            count = manifest["summary"]["total_files"]
            if self.cancelled.is_set():
                self.update(status="cancelled", message="Остановлено. Сохранённые файлы на месте — можно продолжить по той же ссылке.")
            elif not count:
                self.update(status="failed", message="Pinterest не вернул файлы. Проверьте ссылку; если нужен вход, выберите браузер в настройках загрузки.")
            else:
                if make_zip:
                    self.update(status="packing", message="Собираем ZIP-архив…")
                    app.create_zip(board, self.output / (name + ".zip"))
                warnings = manifest["warnings"]
                partial = process.returncode != 0 or bool(warnings)
                self.update(status="partial" if partial else "complete",
                            message=(warnings[0] if warnings else "Часть файлов могла быть недоступна. Подробности в журнале.") if partial
                            else "Загрузка завершена.")
        except Exception as exc:
            self.update(status="failed", message=f"Не удалось завершить загрузку: {exc}")
        finally:
            self.process = None

    def progress(self, board, log):
        files = [p for p in board.iterdir() if p.is_file() and p.suffix.lower() in app.MEDIA_EXTENSIONS]
        try:
            with log.open("rb") as stream:
                stream.seek(max(0, log.stat().st_size - 16000))
                lines = stream.read().decode("utf-8", errors="replace").splitlines()[-60:]
        except OSError:
            lines = []
        self.update(count=len(files), bytes=sum(p.stat().st_size for p in files), lines=lines)


def make_handler(library, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, value):
            payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

        def authorized(self, query):
            candidate = self.headers.get("X-Pinboard-Key") or query.get("key", [""])[0]
            return secrets.compare_digest(candidate, token)

        def file(self, path, attachment=False):
            if not path.is_file():
                return self.reply(404, {"error": "Файл не найден."})
            length = path.stat().st_size
            start, end = 0, length - 1
            requested = self.headers.get("Range")
            if requested:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
                if not match or not any(match.groups()):
                    return self.reply(416, {"error": "Некорректный диапазон."})
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), end) if last else end
                else:
                    start = max(0, length - int(last))
                if start > end or start >= length:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{length}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            self.send_response(206 if requested else 200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            if requested:
                self.send_header("Content-Range", f"bytes {start}-{end}/{length}")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if attachment:
                from urllib.parse import quote
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(path.name))
            self.end_headers()
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = end - start + 1
                try:
                    while remaining and (chunk := stream.read(min(256 * 1024, remaining))):
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass  # A closed preview or video seek can cancel an in-flight request.

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            path = parsed.path
            try:
                if path in {"/", "/app.js", "/style.css", "/icon.svg"}:
                    return self.file(ASSETS / ("index.html" if path == "/" else path[1:]))
                if not self.authorized(query):
                    return self.reply(403, {"error": "Откройте приложение через Pinboard.exe."})
                if path == "/api/state":
                    return self.reply(200, library.state())
                if path == "/api/board":
                    board = library.board_path(query.get("id", [""])[0])
                    manifest = app.read_json(board / "manifest.json") or {}
                    metadata = {i["file"]: i for i in manifest.get("items", [])}
                    items = []
                    for p in sorted(board.iterdir()):
                        if p.is_file() and not p.is_symlink() and p.suffix.lower() in app.MEDIA_EXTENSIONS:
                            items.append({"file": p.name, "kind": app.media_kind(p.suffix),
                                          "title": metadata.get(p.name, {}).get("title") or p.stem,
                                          "bytes": p.stat().st_size})
                    return self.reply(200, {"items": items})
                if path in {"/media", "/zip"}:
                    board = library.board_path(query.get("board", [""])[0])
                    if path == "/zip":
                        return self.file(board.with_name(board.name + ".zip"), True)
                    name = query.get("file", [""])[0]
                    target = (board / name).resolve()
                    if target.parent != board or target.suffix.lower() not in app.MEDIA_EXTENSIONS:
                        return self.reply(403, {"error": "Файл недоступен."})
                    return self.file(target, query.get("save") == ["1"])
                return self.reply(404, {"error": "Страница не найдена."})
            except (app.AppError, OSError, ValueError) as exc:
                self.reply(400, {"error": str(exc)})

        def do_POST(self):
            origin = self.headers.get("Origin")
            expected = f"http://127.0.0.1:{self.server.server_port}"
            if (origin and origin != expected) or not self.authorized({}):
                return self.reply(403, {"error": "Нет доступа."})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 16384:
                    return self.reply(413, {"error": "Слишком большой запрос."})
                data = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(data, dict):
                    raise ValueError("Некорректный запрос.")
                if self.path == "/api/start":
                    library.start(data)
                elif self.path == "/api/stop":
                    library.stop()
                elif self.path == "/api/settings":
                    library.set_output(data.get("output"))
                elif self.path == "/api/open":
                    target = library.board_path(data["board"]) if data.get("board") else library.output
                    target.mkdir(parents=True, exist_ok=True)
                    os.startfile(str(target))
                elif self.path == "/api/quit":
                    if library.job and library.job["status"] in ACTIVE:
                        raise app.AppError("Сначала остановите загрузку и дождитесь сохранения файлов.")
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                else:
                    return self.reply(404, {"error": "Команда не найдена."})
                self.reply(200, {"ok": True})
            except (app.AppError, OSError, ValueError, TypeError) as exc:
                self.reply(400, {"error": str(exc)})
    return Handler


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--gallery-worker":
        with open(sys.argv[2], "w", encoding="utf-8", buffering=1) as log:
            sys.stdout = sys.stderr = log
            sys.argv = ["gallery-dl"] + sys.argv[3:]
            import gallery_dl
            gallery_dl.main()
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--home", type=Path, default=ROOT)
    args = parser.parse_args()
    library = Library(args.home.resolve())
    token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(library, token))
    url = f"http://127.0.0.1:{server.server_port}/#{token}"
    # This file also allows a second launch to reopen the existing instance.
    session_path = args.home / ".pinboard" / "session.json"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    previous = app.read_json(session_path)
    if previous and not args.no_browser:
        try:
            import requests
            response = requests.get(previous["url"].split("#")[0] + "api/state",
                                    headers={"X-Pinboard-Key": previous["url"].split("#")[1]}, timeout=1)
            if response.ok:
                server.server_close()
                webbrowser.open(previous["url"])
                return
        except Exception:
            pass
    app.write_json_atomic(session_path, {"url": url, "pid": os.getpid()})
    if args.no_browser:
        if sys.stdout:
            print(url, flush=True)
    else:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=.3)
    finally:
        server.server_close()
        if library.process and library.process.poll() is None:
            library.process.terminate()


if __name__ == "__main__":
    main()
