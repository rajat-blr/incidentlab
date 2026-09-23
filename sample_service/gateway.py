"""Checkout edge service that forwards requests to the inventory service."""

import json
import os
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from opentelemetry import metrics, propagate, trace
from opentelemetry.trace import SpanKind

from sample_service.telemetry import configure_telemetry, emit_log, request_id_from_header


def make_gateway_handler(inventory_url: str) -> type[BaseHTTPRequestHandler]:
    tracer = trace.get_tracer("incidentlab.checkout")
    meter = metrics.get_meter("incidentlab.checkout")
    requests = meter.create_counter("incidentlab.gateway.requests", unit="1")
    metric_attributes = {"incidentlab.run_id": os.environ.get("INCIDENTLAB_RUN_ID", "manual")}

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status: int, body: bytes, request_id: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            if request_id:
                self.send_header("X-Request-ID", request_id)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._reply(200, b'{"status":"alive"}')
            elif self.path == "/ready":
                try:
                    with urllib.request.urlopen(f"{inventory_url}/ready", timeout=1) as response:
                        body = response.read(1024)
                        self._reply(response.status, body)
                except urllib.error.HTTPError as error:
                    self._reply(error.code, error.read(1024))
                except (urllib.error.URLError, TimeoutError):
                    self._reply(503, b'{"error":"inventory_unavailable"}')
            else:
                self._reply(404, b'{"error":"not_found"}')

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/checkout":
                self._reply(404, b'{"error":"not_found"}')
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 1024:
                    raise ValueError
                body = self.rfile.read(length)
                json.loads(body)
            except (ValueError, UnicodeDecodeError):
                self._reply(400, b'{"error":"invalid_request"}')
                return
            request_id = request_id_from_header(self.headers.get("X-Request-ID"))
            self.request_id = request_id
            context = propagate.extract(self.headers)
            with tracer.start_as_current_span(
                "POST /checkout", context=context, kind=SpanKind.SERVER
            ) as span:
                span.set_attribute("http.route", "/checkout")
                span.set_attribute("incidentlab.request_id", request_id)
                with tracer.start_as_current_span("inventory POST /checkout", kind=SpanKind.CLIENT):
                    headers = {"Content-Type": "application/json", "X-Request-ID": request_id}
                    propagate.inject(headers)
                    request = urllib.request.Request(
                        f"{inventory_url}/checkout", data=body, headers=headers, method="POST"
                    )
                    try:
                        response = urllib.request.urlopen(request, timeout=2)
                    except urllib.error.HTTPError as error:
                        response = error
                    except (urllib.error.URLError, TimeoutError):
                        response = None
                    if response is None:
                        status, result = 503, b'{"error":"inventory_unavailable"}'
                    else:
                        with response:
                            status, result = response.status, response.read(2048)
                span.set_attribute("http.response.status_code", status)
                self._reply(status, result, request_id)
                requests.add(1, {**metric_attributes, "status": str(status)})
                emit_log("gateway_result", request_id, status=status)

        def log_message(self, format: str, *args: object) -> None:
            emit_log("http_request", getattr(self, "request_id", None), message=format % args)

    return Handler


@contextmanager
def running_gateway(inventory_url: str) -> Iterator[ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_gateway_handler(inventory_url))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def main() -> None:
    tracer_provider, meter_provider, logger_provider = configure_telemetry("checkout")
    inventory_url = os.environ.get("INCIDENTLAB_INVENTORY_URL", "http://127.0.0.1:8766")
    port = int(os.environ.get("INCIDENTLAB_PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), make_gateway_handler(inventory_url))
    try:
        print(f"Checkout gateway listening on 127.0.0.1:{port}", flush=True)
        server.serve_forever()
    finally:
        server.server_close()
        logger_provider.shutdown()
        meter_provider.shutdown()
        tracer_provider.shutdown()


if __name__ == "__main__":
    main()
