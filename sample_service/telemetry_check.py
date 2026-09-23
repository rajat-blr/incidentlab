"""Verify Step 3 traces, metrics, and log correlation against the local Compose stack."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from sample_service.demo import post_checkout
from sample_service.reset import reset_database


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=2) as response:
        return json.load(response)


def wait_for(url: str, seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            get_json(url)
            return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.2)
    raise RuntimeError(f"Service did not become ready: {url}")


def find_trace(request_id: str) -> dict | None:
    query = urllib.parse.urlencode({"service": "checkout", "lookback": "1h", "limit": 50})
    for item in get_json(f"http://127.0.0.1:16686/api/traces?{query}").get("data", []):
        for span in item.get("spans", []):
            if any(
                tag.get("key") == "incidentlab.request_id" and tag.get("value") == request_id
                for tag in span.get("tags", [])
            ):
                return item
    return None


def metric_value(name: str, run_id: str) -> float | None:
    expression = f'{name}{{incidentlab_run_id="{run_id}"}}'
    query = urllib.parse.urlencode({"query": expression})
    response = get_json(f"http://127.0.0.1:9090/api/v1/query?{query}")
    values = response.get("data", {}).get("result", [])
    return float(values[0]["value"][1]) if values else None


def loki_events(service_name: str, request_id: str) -> list[dict]:
    expression = f'{{service_name="{service_name}"}} |= "{request_id}"'
    query = urllib.parse.urlencode({"query": expression, "limit": 100})
    response = get_json(f"http://127.0.0.1:3100/loki/api/v1/query_range?{query}")
    events = []
    for stream in response.get("data", {}).get("result", []):
        for _, line in stream.get("values", []):
            event = json.loads(line)
            if event.get("request_id") == request_id:
                events.append(event)
    return events


def read_events(path: Path, request_id: str) -> list[dict]:
    events = []
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("request_id") == request_id:
            events.append(event)
    return events


def main() -> None:
    wait_for("http://127.0.0.1:16686/api/services")
    wait_for("http://127.0.0.1:9090/api/v1/status/buildinfo")
    wait_for("http://127.0.0.1:3100/loki/api/v1/labels")
    with tempfile.TemporaryDirectory(prefix="incidentlab-telemetry-") as temporary:
        root = Path(temporary)
        database = root / "checkout.sqlite3"
        reset_database(database)
        inventory_port, gateway_port = free_port(), free_port()
        request_id = f"step3-{uuid.uuid4().hex[:12]}"
        run_id = request_id
        environment = os.environ.copy()
        environment["INCIDENTLAB_DATABASE"] = str(database)
        environment["INCIDENTLAB_FAULT"] = "pool_leak"
        environment["INCIDENTLAB_RUN_ID"] = run_id
        environment["INCIDENTLAB_PORT"] = str(inventory_port)
        inventory_log = (root / "inventory.log").open("w")
        gateway_log = (root / "gateway.log").open("w")
        processes: list[subprocess.Popen] = []
        try:
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-m", "sample_service.app"],
                    env=environment,
                    stdout=inventory_log,
                    stderr=subprocess.STDOUT,
                )
            )
            wait_for(f"http://127.0.0.1:{inventory_port}/health")
            environment["INCIDENTLAB_INVENTORY_URL"] = f"http://127.0.0.1:{inventory_port}"
            environment["INCIDENTLAB_PORT"] = str(gateway_port)
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-m", "sample_service.gateway"],
                    env=environment,
                    stdout=gateway_log,
                    stderr=subprocess.STDOUT,
                )
            )
            wait_for(f"http://127.0.0.1:{gateway_port}/health")
            statuses = [
                post_checkout(gateway_port, "widget", 99, request_id + "-a")[0],
                post_checkout(gateway_port, "widget", 99, request_id + "-b")[0],
                post_checkout(gateway_port, "widget", 1, request_id)[0],
            ]
            if statuses != [409, 409, 503]:
                raise AssertionError(f"Unexpected replay statuses: {statuses}")

            deadline = time.monotonic() + 20
            trace_data = None
            available = timeout_count = None
            loki_inventory = loki_gateway = []
            while time.monotonic() < deadline:
                trace_data = find_trace(request_id)
                available = metric_value("incidentlab_db_pool_available", run_id)
                timeout_count = metric_value("incidentlab_db_pool_timeouts_total", run_id)
                loki_inventory = loki_events("inventory", request_id)
                loki_gateway = loki_events("checkout", request_id)
                if (
                    trace_data
                    and available == 0
                    and timeout_count is not None
                    and timeout_count >= 1
                    and loki_inventory
                    and loki_gateway
                ):
                    break
                time.sleep(0.5)
            else:
                names = get_json("http://127.0.0.1:9090/api/v1/label/__name__/values")["data"]
                raise AssertionError(
                    f"Telemetry missing: trace={bool(trace_data)}, available={available}, "
                    f"timeouts={timeout_count}, loki_inventory={bool(loki_inventory)}, "
                    f"loki_gateway={bool(loki_gateway)}, "
                    f"incidentlab_metrics={[n for n in names if n.startswith('incidentlab_')]}"
                )

            service_names = {process["serviceName"] for process in trace_data["processes"].values()}
            if not {"checkout", "inventory"}.issubset(service_names):
                raise AssertionError(f"Trace missing a service: {service_names}")
            if not any(
                span["operationName"] == "db.pool.acquire"
                and any(
                    tag.get("key") == "db.pool.timeout" and tag.get("value") is True
                    for tag in span.get("tags", [])
                )
                for span in trace_data["spans"]
            ):
                raise AssertionError("Trace missing the failed database acquisition")

            inventory_log.flush()
            gateway_log.flush()
            inventory_events = read_events(root / "inventory.log", request_id)
            gateway_events = read_events(root / "gateway.log", request_id)
            inventory_result = next(e for e in inventory_events if e["event"] == "checkout_result")
            gateway_result = next(e for e in gateway_events if e["event"] == "gateway_result")
            if (
                not inventory_result["trace_id"]
                or inventory_result["trace_id"] != gateway_result["trace_id"]
            ):
                raise AssertionError("Structured logs do not share one trace ID")
            if inventory_result["trace_id"] != trace_data["traceID"]:
                raise AssertionError("Structured logs do not match the saved trace")
            if not any(event.get("trace_id") == trace_data["traceID"] for event in loki_inventory):
                raise AssertionError("Inventory log in Loki does not match the saved trace")
            if not any(event.get("trace_id") == trace_data["traceID"] for event in loki_gateway):
                raise AssertionError("Gateway log in Loki does not match the saved trace")
            print(
                json.dumps(
                    {
                        "request_id": request_id,
                        "trace_id": trace_data["traceID"],
                        "services": sorted(service_names),
                        "pool_available": available,
                        "pool_timeouts": timeout_count,
                        "statuses": statuses,
                        "logs_in_loki": True,
                    },
                    sort_keys=True,
                )
            )
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            inventory_log.close()
            gateway_log.close()


if __name__ == "__main__":
    main()
