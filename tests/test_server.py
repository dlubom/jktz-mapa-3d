from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from scripts.serve import Handler


class RangeServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "test.bin").write_bytes(bytes(range(32)))
        (self.root / "entry.js").write_text("export {};")
        (self.root / "index.html").write_text("index")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.root = self.root.resolve()
        self.server.prefix = "/jktz-mapa-3d/"
        self.server.request_log = self.root / "requests.jsonl"
        self.server.log_lock = threading.Lock()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def get(self, path, headers=None):
        try:
            return urlopen(Request(self.url + path, headers=headers or {}))
        except HTTPError as response:
            return response

    def test_pages_prefix_range_and_mime(self):
        with self.get("/jktz-mapa-3d/test.bin", {"Range": "bytes=2-6"}) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers["Content-Range"], "bytes 2-6/32")
            self.assertEqual(response.read(), bytes(range(2, 7)))
        with self.get("/jktz-mapa-3d/entry.js") as response:
            self.assertIn("javascript", response.headers["Content-Type"])
        with self.get("/jktz-mapa-3d/") as response:
            self.assertEqual(response.read(), b"index")

    def test_invalid_paths_and_ranges_are_errors(self):
        for path, headers, status in [
            ("/test.bin", {}, 404),
            ("/jktz-mapa-3d/missing", {}, 404),
            ("/jktz-mapa-3d/../outside", {}, 404),
            ("/jktz-mapa-3d/test.bin", {"Range": "bytes=32-40"}, 416),
        ]:
            with self.get(path, headers) as response:
                self.assertEqual(response.status, status)


if __name__ == "__main__":
    unittest.main()
