import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import requests

import app
import desktop


class LocalAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = desktop.Library(self.root)
        board = self.library.output / "artist__inspiration"
        board.mkdir(parents=True)
        (board / "123.jpg").write_bytes(b"image")
        (board / "456.mp4").write_bytes(b"video")
        (self.library.output / "artist__inspiration.zip").write_bytes(b"zip")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), desktop.make_handler(self.library, "test-key"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.headers = {"X-Pinboard-Key": "test-key"}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def test_api_requires_key_and_blocks_other_origins(self):
        self.assertEqual(requests.get(self.url + "/api/state").status_code, 403)
        response = requests.post(self.url + "/api/settings", json={"output": str(self.root / "other")},
                                 headers={**self.headers, "Origin": "https://untrusted.example"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse((self.root / "other").exists())

    def test_imports_existing_boards_without_manifest(self):
        response = requests.get(self.url + "/api/state", headers=self.headers)
        board = response.json()["boards"][0]
        self.assertEqual(board["count"], 2)
        self.assertEqual(board["name"], "inspiration")
        self.assertTrue(board["zip"])
        items = requests.get(self.url + "/api/board", params={"id": board["id"]}, headers=self.headers).json()["items"]
        self.assertEqual({i["kind"] for i in items}, {"image", "video"})

    def test_media_cannot_escape_board(self):
        secret = self.library.output / "secret.jpg"
        secret.write_bytes(b"private")
        response = requests.get(self.url + "/media", params={"key": "test-key", "board": "artist__inspiration", "file": "../secret.jpg"})
        self.assertEqual(response.status_code, 403)
        response = requests.get(self.url + "/media", params={"key": "test-key", "board": "artist__inspiration", "file": "123.jpg"})
        self.assertEqual(response.content, b"image")

    def test_settings_persist_and_reject_relative_path(self):
        response = requests.post(self.url + "/api/settings", json={"output": "relative"}, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        destination = self.root / "new downloads"
        response = requests.post(self.url + "/api/settings", json={"output": str(destination)}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(desktop.Library(self.root).output, destination)

    def test_media_supports_video_seeking(self):
        response = requests.get(self.url + "/media", params={"key": "test-key", "board": "artist__inspiration", "file": "456.mp4"},
                                headers={"Range": "bytes=1-3"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b"ide")
        self.assertEqual(response.headers["Content-Range"], "bytes 1-3/5")

    def test_cancellation_preserves_downloaded_files(self):
        library = self.library

        class FakeProcess:
            returncode = None

            def __init__(self, command, **kwargs):
                log = Path(command[command.index("--gallery-worker") + 1])
                (log.parent / "321.jpg").write_bytes(b"downloaded")
                log.write_text("Saved 321.jpg\n", encoding="utf-8")
                library.cancelled.set()

            def poll(self):
                return self.returncode

            def terminate(self):
                self.returncode = 1

            def wait(self, **kwargs):
                return self.returncode

        with patch.object(desktop.subprocess, "Popen", FakeProcess):
            library.start({"url": "https://pinterest.com/test/cancel/", "zip": True})
            deadline = time.monotonic() + 5
            while library.job["status"] in desktop.ACTIVE and time.monotonic() < deadline:
                time.sleep(.02)
        self.assertEqual(library.job["status"], "cancelled")
        self.assertTrue((library.output / "test__cancel" / "321.jpg").is_file())
        self.assertTrue((library.output / "test__cancel" / "manifest.json").is_file())
        self.assertFalse((library.output / "test__cancel.zip").exists())

    def test_invalid_inputs_do_not_start_worker(self):
        for data in [{"url": "https://example.com/a/b"}, {"url": "https://pinterest.com/a/b", "limit": 0},
                     {"url": "https://pinterest.com/a/b", "browser": "invalid"}, {"url": "ftp://pinterest.com/a/b"}]:
            response = requests.post(self.url + "/api/start", json=data, headers=self.headers)
            self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.library.job)

    def test_busy_state_blocks_second_job_and_folder_change(self):
        self.library.job = {"status": "downloading"}
        with self.assertRaises(app.AppError):
            self.library.start({"url": "https://pinterest.com/a/b/"})
        with self.assertRaises(app.AppError):
            self.library.set_output(str(self.root / "other"))
        self.library.stop()
        self.assertTrue(self.library.cancelled.is_set())
        self.assertEqual(self.library.job["status"], "stopping")

    def test_download_builds_manifest_and_zip(self):
        library = self.library

        class FakeProcess:
            returncode = 0

            def __init__(self, command, **kwargs):
                log = Path(command[command.index("--gallery-worker") + 1])
                (log.parent / "321.jpg").write_bytes(b"downloaded")
                log.write_text("Saved 321.jpg\n", encoding="utf-8")

            def poll(self):
                return 0

        with patch.object(desktop.subprocess, "Popen", FakeProcess):
            library.start({"url": "https://www.pinterest.com/test/board/", "zip": True})
            deadline = time.monotonic() + 5
            while library.job["status"] in desktop.ACTIVE and time.monotonic() < deadline:
                time.sleep(.02)
        self.assertEqual(library.job["status"], "complete")
        manifest = app.read_json(library.output / "test__board" / "manifest.json")
        self.assertEqual(manifest["summary"]["total_files"], 1)
        self.assertTrue((library.output / "test__board.zip").is_file())

    def test_worker_failure_is_reported(self):
        with patch.object(desktop.subprocess, "Popen", side_effect=OSError("worker missing")):
            self.library.start({"url": "https://pinterest.com/test/board"})
            deadline = time.monotonic() + 5
            while self.library.job["status"] in desktop.ACTIVE and time.monotonic() < deadline:
                time.sleep(.02)
        self.assertEqual(self.library.job["status"], "failed")
        self.assertIn("worker missing", self.library.job["message"])

    def test_pin_download_keeps_all_media_and_appears_in_library(self):
        commands = []

        class FakeProcess:
            returncode = 0

            def __init__(self, command, **kwargs):
                commands.append(command)
                log = Path(command[command.index("--gallery-worker") + 1])
                for name in ["123_1.jpg", "123_2.mp4"]:
                    (log.parent / name).write_bytes(b"media")
                (log.parent / "123_1.jpg.json").write_text(json.dumps({
                    "id": "123", "title": "Two pages", "board": {"pin_count": 99}
                }), encoding="utf-8")
                log.write_text("Saved two files\n", encoding="utf-8")

            def poll(self):
                return 0

        with patch.object(desktop.subprocess, "Popen", FakeProcess):
            response = requests.post(self.url + "/api/start", headers=self.headers,
                                     json={"url": "https://pinterest.com/pin/123/", "limit": 1, "zip": True})
            self.assertEqual(response.status_code, 200)
            deadline = time.monotonic() + 5
            while self.library.job["status"] in desktop.ACTIVE and time.monotonic() < deadline:
                time.sleep(.02)
        self.assertNotIn("--range", commands[0])
        self.assertEqual(self.library.job["status"], "complete")
        pin = next(b for b in self.library.boards() if b["id"] == "pin__123")
        self.assertEqual(pin["source_type"], "pin")
        self.assertEqual(pin["count"], 2)
        self.assertEqual(pin["name"], "Two pages")
        self.assertTrue(pin["zip"])


if __name__ == "__main__":
    unittest.main()
