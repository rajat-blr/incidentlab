"""A small checkout HTTP service with an injectable connection leak."""

import json
import os
import queue
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from opentelemetry import metrics, propagate, trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from sample_service.reset import reset_database
from sample_service.telemetry import configure_telemetry, emit_log, request_id_from_header


class PoolTimeout(Exception):
    pass


class DatabasePool:
    def __init__(self, path: Path, size: int = 2, timeout: float = 0.05):
        self.size = size
        self.timeout = timeout
        self._available: queue.Queue[sqlite3.Connection] = queue.Queue(maxsize=size)
        self._connections: list[sqlite3.Connection] = []
        for _ in range(size):
            connection = sqlite3.connect(path, check_same_thread=False)
            self._connections.append(connection)
            self._available.put(connection)

    def acquire(self) -> sqlite3.Connection:
        try:
            return self._available.get(timeout=self.timeout)
        except queue.Empty as exc:
            raise PoolTimeout from exc

    def release(self, connection: sqlite3.Connection) -> None:
        self._available.put_nowait(connection)

    @property
    def available(self) -> int:
        return self._available.qsize()

    def close(self) -> None:
        for connection in self._connections:
            connection.close()


class CheckoutService:
    def __init__(self, database: Path, fault_mode: str = "off"):
        if fault_mode not in {"off", "pool_leak", "inventory_underflow"}:
            raise ValueError(
                "INCIDENTLAB_FAULT must be 'off', 'pool_leak', or 'inventory_underflow'"
            )
        self.pool = DatabasePool(database)
        self.fault_mode = fault_mode
        self._checkout_lock = threading.Lock()
        self.metric_attributes = {
            "incidentlab.run_id": os.environ.get("INCIDENTLAB_RUN_ID", "manual")
        }
        meter = metrics.get_meter("incidentlab.inventory")
        self.pool_timeouts = meter.create_counter("incidentlab.db.pool.timeouts", unit="1")
        self.checkout_requests = meter.create_counter("incidentlab.checkout.requests", unit="1")
        self.pool_available = meter.create_observable_gauge(
            "incidentlab.db.pool.available",
            callbacks=[
                lambda _: [metrics.Observation(self.pool.available, self.metric_attributes)]
            ],
            unit="{connection}",
        )

    def checkout(self, sku: str, quantity: int, request_id: str | None = None) -> tuple[int, dict]:
        tracer = trace.get_tracer("incidentlab.inventory")
        with tracer.start_as_current_span("db.pool.acquire") as acquire_span:
            try:
                connection = self.pool.acquire()
                acquire_span.set_attribute("db.pool.available_after_acquire", self.pool.available)
            except PoolTimeout:
                self.pool_timeouts.add(1, self.metric_attributes)
                acquire_span.set_status(Status(StatusCode.ERROR, "database_pool_timeout"))
                acquire_span.set_attribute("db.pool.timeout", True)
                emit_log("database_pool_timeout", request_id, available=self.pool.available)
                return 503, {"error": "database_pool_timeout"}

        return_connection = True
        with self._checkout_lock:
            try:
                with tracer.start_as_current_span("db.inventory.query"):
                    row = connection.execute(
                        "SELECT quantity FROM inventory WHERE sku = ?", (sku,)
                    ).fetchone()
                if row is None:
                    return 404, {"error": "unknown_sku"}
                if row[0] < quantity and self.fault_mode != "inventory_underflow":
                    if self.fault_mode == "pool_leak":
                        # Intentional incident fixture: this branch leaves its slot checked out.
                        return_connection = False
                    return 409, {"error": "out_of_stock"}
                remaining = row[0] - quantity
                connection.execute(
                    "UPDATE inventory SET quantity = ? WHERE sku = ?", (remaining, sku)
                )
                connection.commit()
                return 200, {"sku": sku, "remaining_inventory": remaining}
            finally:
                if return_connection:
                    self.pool.release(connection)


def make_handler(service: CheckoutService) -> type[BaseHTTPRequestHandler]:
    tracer = trace.get_tracer("incidentlab.inventory")

    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, body: dict) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802 (stdlib method name)
            if self.path == "/health":
                self._json(200, {"status": "alive"})
            elif self.path == "/ready":
                status = 200 if service.pool.available else 503
                self._json(status, {"database_connections_available": service.pool.available})
            else:
                self._json(404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802 (stdlib method name)
            if self.path != "/checkout":
                self._json(404, {"error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 1024:
                    raise ValueError
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or set(data) != {"sku", "quantity"}:
                    raise ValueError
                if not isinstance(data["sku"], str) or not data["sku"]:
                    raise ValueError
                if type(data["quantity"]) is not int or data["quantity"] < 1:
                    raise ValueError
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                self._json(400, {"error": "invalid_request"})
                return
            request_id = request_id_from_header(self.headers.get("X-Request-ID"))
            context = propagate.extract(self.headers)
            with tracer.start_as_current_span(
                "POST /checkout", context=context, kind=SpanKind.SERVER
            ) as span:
                span.set_attribute("http.route", "/checkout")
                span.set_attribute("incidentlab.request_id", request_id)
                status, body = service.checkout(data["sku"], data["quantity"], request_id)
                span.set_attribute("http.response.status_code", status)
                self.request_id = request_id
                self._json(status, body)
                service.checkout_requests.add(
                    1, {**service.metric_attributes, "status": str(status)}
                )
                emit_log(
                    "checkout_result",
                    request_id,
                    status=status,
                    pool_available=service.pool.available,
                )

        def log_message(self, format: str, *args: object) -> None:
            emit_log("http_request", getattr(self, "request_id", None), message=format % args)

    return Handler


@contextmanager
def running_server(service: CheckoutService) -> Iterator[ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        service.pool.close()


def main() -> None:
    database = Path(os.environ.get("INCIDENTLAB_DATABASE", "/tmp/incidentlab-checkout.sqlite3"))
    if not database.exists():
        reset_database(database)
    tracer_provider, meter_provider, logger_provider = configure_telemetry("inventory")
    service = CheckoutService(database, os.environ.get("INCIDENTLAB_FAULT", "off"))
    port = int(os.environ.get("INCIDENTLAB_PORT", "8766"))
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(service))
    try:
        print(f"Checkout service listening on 127.0.0.1:{port}", flush=True)
        server.serve_forever()
    finally:
        server.server_close()
        service.pool.close()
        logger_provider.shutdown()
        meter_provider.shutdown()
        tracer_provider.shutdown()


if __name__ == "__main__":
    main()
