"""Runtime scenario catalog, without private root-cause or repair labels."""

SCENARIOS = {
    "pool-exhaustion": {
        "fault_mode": "pool_leak",
        "gateway_fault_mode": "off",
        "source_path": "sample_service/app.py",
        "traffic": (("widget", 99), ("widget", 99), ("widget", 1)),
        "fault_statuses": [409, 409, 503],
        "healthy_statuses": [409, 409, 200],
        "fault_remaining": [None, None, None],
        "healthy_remaining": [None, None, 9],
    },
    "inventory-underflow": {
        "fault_mode": "inventory_underflow",
        "gateway_fault_mode": "off",
        "source_path": "sample_service/app.py",
        "traffic": (("widget", 11),),
        "fault_statuses": [200],
        "healthy_statuses": [409],
        "fault_remaining": [-1],
        "healthy_remaining": [None],
    },
    "upstream-error-masking": {
        "fault_mode": "off",
        "gateway_fault_mode": "status_masking",
        "source_path": "sample_service/gateway.py",
        "traffic": (("widget", 99),),
        "fault_statuses": [200],
        "healthy_statuses": [409],
        "fault_remaining": [None],
        "healthy_remaining": [None],
    },
    "mutation-response-cache": {
        "fault_mode": "off",
        "gateway_fault_mode": "mutation_cache",
        "source_path": "sample_service/gateway.py",
        "traffic": (("widget", 1), ("widget", 1)),
        "fault_statuses": [200, 200],
        "healthy_statuses": [200, 200],
        "fault_remaining": [9, 9],
        "healthy_remaining": [9, 8],
    },
}


def matches_results(scenario_id: str, results: list[tuple[int, dict]], *, healthy: bool) -> bool:
    scenario = SCENARIOS[scenario_id]
    prefix = "healthy" if healthy else "fault"
    return (
        [status for status, _ in results] == scenario[f"{prefix}_statuses"]
        and [body.get("remaining_inventory") for _, body in results]
        == scenario[f"{prefix}_remaining"]
        and (
            scenario_id != "upstream-error-masking" or results[-1][1].get("error") == "out_of_stock"
        )
        and (
            scenario_id != "pool-exhaustion"
            or healthy
            or results[-1][1].get("error") == "database_pool_timeout"
        )
    )
