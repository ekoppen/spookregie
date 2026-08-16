import threading

import cv2
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from http.server import HTTPServer

_BOUNDARY = "frame"


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class MJPEGStreamer:
    """Serveert het laatst gepubliceerde frame als MJPEG over HTTP op
    `/stream`. `publish_frame()` wordt vanuit de hoofdloop aangeroepen;
    elke binnenkomende HTTP-verbinding krijgt zijn eigen thread die
    steeds het nieuwste frame stuurt (multipart/x-mixed-replace)."""

    def __init__(self, port):
        self._port = port
        self._frame_lock = threading.Lock()
        self._latest_jpeg = None
        self._server = None

    def publish_frame(self, frame_bgr):
        ok, encoded = cv2.imencode(".jpg", frame_bgr)
        if not ok:
            return
        with self._frame_lock:
            self._latest_jpeg = encoded.tobytes()

    def _get_latest_jpeg(self):
        with self._frame_lock:
            return self._latest_jpeg

    def start(self):
        streamer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def do_GET(self):
                if self.path != "/stream":
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
                )
                self.end_headers()
                try:
                    while True:
                        jpeg = streamer._get_latest_jpeg()
                        if jpeg is None:
                            continue
                        self.wfile.write(f"--{_BOUNDARY}\r\n".encode())
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self._server = _ThreadingHTTPServer(("0.0.0.0", self._port), Handler)
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
