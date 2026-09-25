"""Run the incident in instrumented service processes and return its query window."""

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sample_service.demo import post_checkout
from sample_service.reset import reset_database


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for(url: str, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.1)
    raise RuntimeError(f"service did not become ready: {url}")


SCENARIO_REPLAYS = {
    "pool-exhaustion": {
        "fault_mode": "pool_leak",
        "traffic": (("widget", 99), ("widget", 99), ("widget", 1)),
        "suffixes": ("a", "b", "failure"),
    },
    "inventory-underflow": {
        "fault_mode": "inventory_underflow",
        "traffic": (("widget", 11),),
        "suffixes": ("failure",),
    },
}


def replay_with_telemetry(
    database: Path, run_id: str, log_dir: Path, scenario_id: str = "pool-exhaustion"
) -> dict:
    scenario = SCENARIO_REPLAYS.get(scenario_id)
    if scenario is None:
        raise ValueError(f"unsupported scenario: {scenario_id}")
    reset_database(database)
    inventory_port, gateway_port = _free_port(), _free_port()
    root_id = f"run-{run_id[:8]}-{uuid.uuid4().hex[:8]}"
    request_ids = [f"{root_id}-{suffix}" for suffix in scenario["suffixes"]]
    environment = {
        **os.environ,
        "INCIDENTLAB_DATABASE": str(database),
        "INCIDENTLAB_FAULT": scenario["fault_mode"],
        "INCIDENTLAB_RUN_ID": run_id,
        "INCIDENTLAB_PORT": str(inventory_port),
        "OTEL_BSP_SCHEDULE_DELAY": "200",
    }
    inventory_log = (log_dir / "inventory.log").open("wb")
    gateway_log = (log_dir / "gateway.log").open("wb")
    processes: list[subprocess.Popen] = []
    started = datetime.now(UTC) - timedelta(seconds=2)
    try:
        processes.append(
            subprocess.Popen(
                [sys.executable, "-m", "sample_service.app"],
                env=environment,
                stdout=inventory_log,
                stderr=subprocess.STDOUT,
            )
        )
        _wait_for(f"http://127.0.0.1:{inventory_port}/health")
        gateway_environment = {
            **environment,
            "INCIDENTLAB_INVENTORY_URL": f"http://127.0.0.1:{inventory_port}",
            "INCIDENTLAB_PORT": str(gateway_port),
        }
        processes.append(
            subprocess.Popen(
                [sys.executable, "-m", "sample_service.gateway"],
                env=gateway_environment,
                stdout=gateway_log,
                stderr=subprocess.STDOUT,
            )
        )
        _wait_for(f"http://127.0.0.1:{gateway_port}/health")
        results = [
            post_checkout(gateway_port, sku, quantity, request_id)
            for (sku, quantity), request_id in zip(scenario["traffic"], request_ids, strict=True)
        ]
        # Allow one metric export and Collector/Prometheus scrape before shutdown.
        time.sleep(2.25)
        return {
            "statuses": [status for status, _ in results],
            "failure": results[-1][1].get("error"),
            "response": results[-1][1],
            "request_ids": request_ids,
            "observed_start": started.isoformat(),
            "observed_end": (datetime.now(UTC) + timedelta(seconds=2)).isoformat(),
        }
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        inventory_log.close()
        gateway_log.close()
