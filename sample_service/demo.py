"""Replay the first incident and its healthy control against the HTTP service."""

import argparse
import json
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from sample_service.app import CheckoutService, running_server
from sample_service.gateway import running_gateway
from sample_service.reset import reset_database


def post_checkout(
    port: int, sku: str, quantity: int, request_id: str | None = None
) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if request_id:
        headers["X-Request-ID"] = request_id
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/checkout",
        data=json.dumps({"sku": sku, "quantity": quantity}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        response = urllib.request.urlopen(request, timeout=2)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


def replay(database: Path, fault_mode: str) -> list[tuple[int, dict]]:
    return replay_traffic(database, fault_mode, (("widget", 99), ("widget", 99), ("widget", 1)))


def replay_traffic(
    database: Path,
    fault_mode: str,
    traffic: tuple[tuple[str, int], ...],
) -> list[tuple[int, dict]]:
    reset_database(database)
    service = CheckoutService(database, fault_mode)
    with running_server(service) as server:
        with running_gateway(f"http://127.0.0.1:{server.server_port}") as gateway:
            port = gateway.server_port
            return [post_checkout(port, sku, quantity) for sku, quantity in traffic]


def replay_inventory_underflow(database: Path, fault_mode: str) -> list[tuple[int, dict]]:
    return replay_traffic(database, fault_mode, (("widget", 11),))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=20)
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials must be positive")
    expected_fault = [409, 409, 503]
    expected_healthy = [409, 409, 200]
    with tempfile.TemporaryDirectory(prefix="incidentlab-demo-") as temporary:
        database = Path(temporary) / "checkout.sqlite3"
        fault_passes = 0
        healthy_passes = 0
        for _ in range(args.trials):
            fault_passes += [
                status for status, _ in replay(database, "pool_leak")
            ] == expected_fault
            healthy_passes += [status for status, _ in replay(database, "off")] == expected_healthy
    print(
        json.dumps(
            {
                "trials": args.trials,
                "fault_reproductions": fault_passes,
                "healthy_controls": healthy_passes,
            },
            sort_keys=True,
        )
    )
    if fault_passes != args.trials or healthy_passes != args.trials:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
