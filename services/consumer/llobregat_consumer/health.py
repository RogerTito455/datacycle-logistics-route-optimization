"""A small HTTP health endpoint: GET /health answers 200 when the consumer is healthy, 503 when not.

The body is the consumer's status as JSON: partitions, lag, messages, rows and dead letters. The
Compose healthcheck calls it from inside the container.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from llobregat_consumer.consumer import Status


def serve(status: Status, port: int, clock=time.monotonic) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.split("?")[0] not in ("/", "/health"):
                self.send_error(404)
                return
            healthy, report = status.report(clock())
            body = json.dumps(report).encode()
            self.send_response(200 if healthy else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:  # the healthcheck calls every few seconds
            pass

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, name="health", daemon=True).start()
    return server
