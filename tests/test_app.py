import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app


class UrlTests(unittest.TestCase):
    def test_public_board_url(self):
        url, name = app.parse_board_url(
            "https://www.pinterest.com/example/My%20Board/"
        )
        self.assertEqual(url, "https://www.pinterest.com/example/My%20Board/")
        self.assertEqual(name, "example__My Board")

    def test_regional_domain(self):
        _, name = app.parse_board_url("https://in.pinterest.com/user/ideas/")
        self.assertEqual(name, "user__ideas")

    def test_tracking_query_is_removed(self):
        url, _ = app.parse_board_url(
            "https://ru.pinterest.com/user/board/?invite_code=secret&sender=123"
        )
        self.assertEqual(url, "https://ru.pinterest.com/user/board/")

    def test_short_url_falls_back_when_resolution_fails(self):
        original_get = app.requests.get
        app.requests.get = lambda *args, **kwargs: (_ for _ in ()).throw(
            app.requests.RequestException("offline")
        )
        try:
            url, name = app.parse_board_url("https://pin.it/abc123")
        finally:
            app.requests.get = original_get
        self.assertEqual(url, "https://pin.it/abc123")
        self.assertEqual(name, "pinterest-board-abc123")

    def test_pin_urls_are_canonical_and_do_not_include_related_pins(self):
        for raw in ["https://www.pinterest.com/pin/123/?foo=1#related",
                    "www.pinterest.com/pin/a-long-title--123/", "http://www.pinterest.com/pin/123/"]:
            with self.subTest(raw=raw):
                self.assertEqual(app.parse_pinterest_url(raw),
                                 ("https://www.pinterest.com/pin/123/", "pin__123"))

    def test_invalid_pin_urls_are_rejected(self):
        for raw in ["https://pinterest.com/pin/", "https://pinterest.com/pin/abc/",
                    "https://pinterest.com/pin/123/related/", "https://user:pass@pinterest.com/pin/123/",
                    "ftp://pinterest.com/pin/123/", "https://pinterest.com.evil.example/pin/123/"]:
            with self.subTest(raw=raw), self.assertRaises(app.AppError):
                app.parse_pinterest_url(raw)

    def test_short_url_resolves_to_pin(self):
        with patch.object(app.requests, "get", return_value=Mock(url="https://ru.pinterest.com/pin/123/?sender=42")):
            self.assertEqual(app.parse_pinterest_url("https://pin.it/example"),
                             ("https://ru.pinterest.com/pin/123/", "pin__123"))

    def test_limit_only_applies_to_board(self):
        root = Path("downloads")
        for url, limited in [("https://pinterest.com/user/board/", True),
                             ("https://pinterest.com/pin/123/", False)]:
            command = app.build_gallery_command(url, root, root / ".pbd", root / "log", 1, None)
            self.assertEqual("--range" in command, limited)

    def test_unrelated_domain_is_rejected(self):
        with self.assertRaises(app.AppError):
            app.parse_board_url("https://pinterest.example.com/user/board/")


class ManifestTests(unittest.TestCase):
    def test_manifest_counts_media(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            board = root / "board"
            metadata = board / ".pbd" / "metadata"
            metadata.mkdir(parents=True)
            (board / "123.jpg").write_bytes(b"image")
            (board / "456.mp4").write_bytes(b"video-data")
            (metadata / "123.jpg.json").write_text(
                json.dumps(
                    {
                        "id": "123",
                        "title": "Example",
                        "board": {
                            "id": "b1",
                            "name": "Board",
                            "pin_count": 2,
                            "privacy": "public",
                            "owner": {"username": "user"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            log = board / "download.log"
            log.write_text("", encoding="utf-8")

            manifest = app.build_manifest(
                "https://www.pinterest.com/user/board/",
                board,
                metadata,
                log,
                0,
            )

            self.assertEqual(manifest["status"], "ok")
            self.assertEqual(manifest["summary"]["total_files"], 2)
            self.assertEqual(manifest["summary"]["image_files"], 1)
            self.assertEqual(manifest["summary"]["video_files"], 1)
            self.assertEqual(manifest["board"]["username"], "user")

    def test_manifest_warns_about_missing_declared_pins(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            board = root / "board"
            metadata = board / ".pbd" / "metadata"
            metadata.mkdir(parents=True)
            (board / "123.jpg").write_bytes(b"image")
            (metadata / "123.jpg.json").write_text(
                json.dumps(
                    {
                        "id": "123",
                        "board": {
                            "id": "b1",
                            "name": "Board",
                            "pin_count": 2,
                            "owner": {"username": "user"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            log = board / "download.log"
            log.write_text("", encoding="utf-8")

            manifest = app.build_manifest(
                "https://www.pinterest.com/user/board/",
                board,
                metadata,
                log,
                0,
            )

            self.assertEqual(manifest["status"], "ok_with_warnings")
            self.assertEqual(len(manifest["warnings"]), 1)

            # A pin's parent board can contain many other pins; this is not a partial download.
            manifest = app.build_manifest("https://pinterest.com/pin/123/", board, metadata, log, 0)
            self.assertEqual(manifest["status"], "ok")
            self.assertEqual(manifest["source_type"], "pin")

    def test_limit_suppresses_declared_pin_warning(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            board = root / "board"
            metadata = board / ".pbd" / "metadata"
            metadata.mkdir(parents=True)
            (board / "123.jpg").write_bytes(b"image")
            (metadata / "123.jpg.json").write_text(
                json.dumps(
                    {
                        "id": "123",
                        "board": {
                            "pin_count": 100,
                            "owner": {"username": "user"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            log = board / "download.log"
            log.write_text("", encoding="utf-8")

            manifest = app.build_manifest(
                "https://www.pinterest.com/user/board/",
                board,
                metadata,
                log,
                0,
                limit=1,
            )

            self.assertEqual(manifest["status"], "ok")
            self.assertEqual(manifest["warnings"], [])


if __name__ == "__main__":
    unittest.main()
