#!/usr/bin/env python3
"""Static prototype server with project-path routing and single HTTP byte ranges."""

import argparse
import json
import mimetypes
import re
import threading
from datetime import datetime, timezone
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_HEAD(self):
        self.serve_file(head=True)

    def do_GET(self):
        self.serve_file(head=False)

    def log_message(self, *_args):
        pass

    def reply(self, status, length, headers=None):
        self.send_response(status)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-cache")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        entry = {
            "time": datetime.now(timezone.utc).isoformat(),
            "method": self.command,
            "path": self.path,
            "range": self.headers.get("Range"),
            "status": status,
            "content_length": length,
            "content_range": (headers or {}).get("Content-Range"),
        }
        with self.server.log_lock:
            with self.server.request_log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry) + "\n")

    def serve_file(self, head):
        route = unquote(urlsplit(self.path).path)
        if not route.startswith(self.server.prefix):
            self.reply(404, 0)
            return
        path = (self.server.root / route[len(self.server.prefix) :]).resolve()
        if path != self.server.root and self.server.root not in path.parents:
            self.reply(404, 0)
            return
        if path.is_dir():
            path = path / "index.html"
        if not path.is_file():
            self.reply(404, 0)
            return

        with path.open("rb") as stream:
            stat = path.stat()
            size = stat.st_size
            start, end, status = 0, size - 1, 200
            mime = {
                ".js": "text/javascript",
                ".mjs": "text/javascript",
                ".wgsl": "text/plain",
                ".bin": "application/octet-stream",
                ".wasm": "application/wasm",
            }.get(
                path.suffix,
                mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            )
            headers = {
                "Content-Type": mime,
                "Accept-Ranges": "bytes",
                "Last-Modified": formatdate(stat.st_mtime, usegmt=True),
            }
            requested_range = self.headers.get("Range", "")
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested_range)
            if match and any(match.groups()) and self.command == "GET":
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), size - 1) if last else size - 1
                else:
                    start = max(0, size - int(last))
                if size == 0 or start >= size or end < start:
                    headers["Content-Range"] = f"bytes */{size}"
                    self.reply(416, 0, headers)
                    return
                status = 206
                headers["Content-Range"] = f"bytes {start}-{end}/{size}"
            length = max(0, end - start + 1)
            self.reply(status, length, headers)
            if head:
                return
            stream.seek(start)
            remaining = length
            try:
                while remaining:
                    block = stream.read(min(1024 * 1024, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)
            except (BrokenPipeError, ConnectionResetError):
                pass


def main():
    base = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=base / "dist")
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--prefix", default="/jktz-mapa-3d/")
    parser.add_argument("--log", type=Path, default=base / ".build/requests.jsonl")
    args = parser.parse_args()
    if not args.prefix.startswith("/") or not args.prefix.endswith("/"):
        parser.error("prefix must start and end with /")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.root = args.root.resolve()
    server.prefix = args.prefix
    server.request_log = args.log
    server.log_lock = threading.Lock()
    print(
        f"Static site: http://127.0.0.1:{server.server_port}{args.prefix}", flush=True
    )
    print(f"Root: {server.root}; request log: {args.log}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
