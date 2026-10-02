from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse, urlunparse

import requests


APP_VERSION = "1.1.0"
MEDIA_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
    ".mkv",
    ".mp3",
    ".m4a",
    ".aac",
    ".wav",
    ".txt",
}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav"}
WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
PINTEREST_DOMAINS = {
    "pinterest.com",
    "pinterest.at",
    "pinterest.be",
    "pinterest.ca",
    "pinterest.ch",
    "pinterest.cl",
    "pinterest.co.kr",
    "pinterest.co.uk",
    "pinterest.com.au",
    "pinterest.com.mx",
    "pinterest.cz",
    "pinterest.de",
    "pinterest.dk",
    "pinterest.es",
    "pinterest.fi",
    "pinterest.fr",
    "pinterest.ie",
    "pinterest.it",
    "pinterest.jp",
    "pinterest.nl",
    "pinterest.no",
    "pinterest.nz",
    "pinterest.ph",
    "pinterest.pl",
    "pinterest.pt",
    "pinterest.ru",
    "pinterest.se",
}


class AppError(RuntimeError):
    pass


def parse_pinterest_url(raw_url: str) -> tuple[str, str]:
    url = raw_url.strip()
    if not url:
        raise AppError("Ссылка на Pinterest не указана.")
    if "://" not in url:
        url = "https://" + url

    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or parsed.username or parsed.password:
        raise AppError("Укажите https-ссылку на доску или пин Pinterest.")
    host = (parsed.hostname or "").lower().rstrip(".")
    if host == "pin.it":
        try:
            response = requests.get(
                url,
                allow_redirects=True,
                stream=True,
                timeout=20,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resolved_url = response.url
            response.close()
            resolved_host = (urlparse(resolved_url).hostname or "").lower().rstrip(".")
            if any(
                resolved_host == domain or resolved_host.endswith("." + domain)
                for domain in PINTEREST_DOMAINS
            ):
                return parse_pinterest_url(resolved_url)
        except requests.RequestException:
            pass
        token = next((part for part in parsed.path.split("/") if part), "board")
        return url, safe_name(f"pinterest-board-{token}")

    if not any(host == domain or host.endswith("." + domain) for domain in PINTEREST_DOMAINS):
        raise AppError("Ожидалась ссылка на pinterest.com или региональный домен Pinterest.")

    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if parts and parts[0].lower() == "pin":
        match = re.fullmatch(r"(?:[^/]+--)?([0-9]+)", parts[1]) if len(parts) == 2 else None
        if not match:
            raise AppError("Нужна ссылка на пин вида https://www.pinterest.com/pin/123456789/.")
        pin_id = match[1]
        return f"https://{host}/pin/{pin_id}/", f"pin__{pin_id}"
    if len(parts) < 2 or parts[0].lower() in {"search", "ideas", "settings", "login"}:
        raise AppError(
            "Нужна ссылка на доску или отдельный пин Pinterest."
        )

    username, board_slug = parts[0], parts[1]
    clean_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return clean_url, safe_name(f"{username}__{board_slug}")


# Keep compatibility with earlier command-line integrations.
parse_board_url = parse_pinterest_url


def source_kind(url: str) -> str:
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() == "pin.it":
        return "shared"
    return "pin" if parsed.path.lower().startswith("/pin/") else "board"


def safe_name(value: str, max_length: int = 120) -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if not value:
        value = "pinterest-board"
    if value.upper() in WINDOWS_RESERVED:
        value = "_" + value
    return value[:max_length].rstrip(" .")


def build_gallery_command(
    url: str,
    board_dir: Path,
    state_dir: Path,
    log_path: Path,
    limit: int | None,
    cookies_from_browser: str | None,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "gallery_dl",
        "--config-ignore",
        "--directory",
        str(board_dir),
        "--filename",
        "{id}{media_id|page_id:?_//}.{extension}",
        "--windows-filenames",
        "--write-metadata",
        "--download-archive",
        str(state_dir / "archive.txt"),
        "--option",
        "extractor.pinterest.sections=true",
        "--option",
        "extractor.pinterest.stories=true",
        "--option",
        "extractor.pinterest.videos=true",
        "--option",
        "downloader.part=true",
        "--option",
        "downloader.retries=4",
    ]
    # A pin can contain several media files: never truncate it with a board limit.
    if limit is not None and source_kind(url) == "board":
        command.extend(("--range", f"1-{limit}"))
    if cookies_from_browser:
        command.extend(("--cookies-from-browser", cookies_from_browser))
    command.append(url)
    return command


def run_and_tee(command: list[str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
        stamp = datetime.now(timezone.utc).isoformat()
        log_file.write(f"\n=== pinterest-board-downloader {APP_VERSION} at {stamp} ===\n")
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        except OSError as exc:
            raise AppError(f"Не удалось запустить загрузчик: {exc}") from exc

        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            log_file.write(line)
        return process.wait()


def move_metadata(board_dir: Path, metadata_dir: Path) -> None:
    metadata_dir.mkdir(parents=True, exist_ok=True)
    for sidecar in board_dir.glob("*.json"):
        if sidecar.name == "manifest.json":
            continue
        destination = metadata_dir / sidecar.name
        if destination.exists():
            destination.unlink()
        shutil.move(str(sidecar), str(destination))


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def media_kind(extension: str) -> str:
    suffix = extension.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix == ".txt":
        return "text"
    return "other"


def collect_error_lines(log_path: Path, maximum: int = 100) -> list[str]:
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    errors = [
        line.strip()
        for line in lines
        if "[error]" in line.lower()
        or "error when" in line.lower()
        or "failed" in line.lower()
    ]
    return errors[-maximum:]


def build_manifest(
    board_url: str,
    board_dir: Path,
    metadata_dir: Path,
    log_path: Path,
    exit_code: int,
    limit: int | None = None,
) -> dict[str, Any]:
    metadata_by_media: dict[str, dict[str, Any]] = {}
    for sidecar in metadata_dir.glob("*.json"):
        metadata = read_json(sidecar)
        if metadata is not None:
            metadata_by_media[sidecar.name[:-5]] = metadata

    items: list[dict[str, Any]] = []
    board_info: dict[str, Any] = {}
    unique_pin_ids: set[str] = set()
    counts = {"image": 0, "video": 0, "audio": 0, "text": 0, "other": 0}
    total_bytes = 0

    for path in sorted(board_dir.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
            continue
        metadata = metadata_by_media.get(path.name, {})
        pin_id = str(metadata.get("id") or path.stem.split("_", 1)[0])
        if pin_id:
            unique_pin_ids.add(pin_id)
        board = metadata.get("board")
        if isinstance(board, dict) and not board_info:
            owner = board.get("owner") if isinstance(board.get("owner"), dict) else {}
            board_info = {
                "id": board.get("id"),
                "name": board.get("name"),
                "username": owner.get("username"),
                "declared_pin_count": board.get("pin_count"),
                "privacy": board.get("privacy"),
            }

        size = path.stat().st_size
        kind = media_kind(path.suffix)
        counts[kind] += 1
        total_bytes += size
        description = (
            metadata.get("description")
            or metadata.get("closeup_unified_description")
            or metadata.get("seo_alt_text")
            or metadata.get("auto_alt_text")
        )
        items.append(
            {
                "file": path.name,
                "bytes": size,
                "kind": kind,
                "pin_id": pin_id or None,
                "pin_url": f"https://www.pinterest.com/pin/{pin_id}/" if pin_id else None,
                "title": metadata.get("title") or metadata.get("grid_title"),
                "description": description,
                "width": metadata.get("width"),
                "height": metadata.get("height"),
                "duration_ms": metadata.get("duration"),
                "media_url": metadata.get("url"),
            }
        )

    errors = collect_error_lines(log_path)
    warnings: list[str] = []
    declared_pin_count = board_info.get("declared_pin_count")
    if (
        source_kind(board_url) == "board"
        and limit is None
        and isinstance(declared_pin_count, int)
        and len(unique_pin_ids) < declared_pin_count
    ):
        warnings.append(
            f"Pinterest сообщает о {declared_pin_count} пинах, но файлы доступны "
            f"для {len(unique_pin_ids)}. Разница может состоять из удалённых, "
            "недоступных или служебных элементов веб-ленты."
        )

    if exit_code != 0 or not items:
        status = "partial_or_failed"
    elif warnings:
        status = "ok_with_warnings"
    else:
        status = "ok"

    return {
        "app": {"name": "pinterest-board-downloader", "version": APP_VERSION},
        "board_url": board_url,
        "source_type": source_kind(board_url),
        "board": board_info,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "gallery_dl_exit_code": exit_code,
        "requested_limit": limit if source_kind(board_url) == "board" else None,
        "summary": {
            "unique_pins_with_files": len(unique_pin_ids),
            "total_files": len(items),
            "total_bytes": total_bytes,
            **{f"{kind}_files": count for kind, count in counts.items()},
        },
        "warnings": warnings,
        "errors": errors,
        "items": items,
    }


def write_json_atomic(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def create_zip(board_dir: Path, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(board_dir.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file():
                continue
            if path.name == "download.log" or path.suffix == ".part":
                continue
            archive.write(path, arcname=f"{board_dir.name}/{path.name}")
    os.replace(temporary, destination)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Скачать доску или отдельный пин Pinterest.",
    )
    parser.add_argument("url", help="Ссылка на доску или пин Pinterest")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("downloads"),
        help="Каталог для загрузок (по умолчанию: downloads)",
    )
    parser.add_argument("--zip", action="store_true", help="Дополнительно создать ZIP")
    parser.add_argument(
        "--limit",
        type=int,
        help="Скачать только первые N пинов (удобно для проверки)",
    )
    parser.add_argument(
        "--cookies-from-browser",
        choices=("chrome", "edge", "firefox"),
        help="Использовать сессию локального браузера, если Pinterest требует вход",
    )
    parser.add_argument("--version", action="version", version=APP_VERSION)
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit должен быть положительным числом")
    return args


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(argv)
    try:
        board_url, directory_name = parse_pinterest_url(args.url)
        output_root = args.output.expanduser().resolve()
        board_dir = output_root / directory_name
        state_dir = board_dir / ".pbd"
        metadata_dir = state_dir / "metadata"
        log_path = board_dir / "download.log"

        board_dir.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)

        print(f"Источник: {board_url}")
        print(f"Папка: {board_dir}")
        command = build_gallery_command(
            board_url,
            board_dir,
            state_dir,
            log_path,
            args.limit,
            args.cookies_from_browser,
        )
        exit_code = run_and_tee(command, log_path)
        move_metadata(board_dir, metadata_dir)
        manifest = build_manifest(
            board_url,
            board_dir,
            metadata_dir,
            log_path,
            exit_code,
            args.limit,
        )
        manifest_path = board_dir / "manifest.json"
        write_json_atomic(manifest_path, manifest)

        zip_path: Path | None = None
        if args.zip and manifest["summary"]["total_files"]:
            zip_path = output_root / f"{directory_name}.zip"
            print(f"Создаю ZIP: {zip_path}")
            create_zip(board_dir, zip_path)

        summary = manifest["summary"]
        print("\nГотово:")
        print(f"  пинов с файлами: {summary['unique_pins_with_files']}")
        print(f"  файлов: {summary['total_files']}")
        print(f"  изображений: {summary['image_files']}")
        print(f"  видео: {summary['video_files']}")
        for warning in manifest["warnings"]:
            print(f"  предупреждение: {warning}")
        print(f"  результат: {board_dir}")
        if zip_path:
            print(f"  ZIP: {zip_path}")

        if not summary["total_files"]:
            raise AppError(
                "Pinterest не вернул ни одного файла. Проверьте ссылку и download.log; "
                "при необходимости попробуйте --cookies-from-browser edge."
            )
        return 0 if exit_code == 0 else 2
    except AppError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nОстановлено пользователем.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
