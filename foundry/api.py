"""Framework-agnostic HTTP router for scientist queries, lineage audit, and governance-safe exports."""
from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import parse_qs

from .dual_store import MaterialsDualStore


def dispatch_request(
    store: MaterialsDualStore,
    method: str,
    path: str,
    query_string: str = "",
) -> tuple[int, dict[str, str], dict[str, Any]]:
    qs = parse_qs(query_string)

    if method == "GET" and path == "/api/v1/candidates":
        release_id = qs.get("release_id", [""])[0]
        viewer_org = qs.get("viewer_org", ["public"])[0]
        min_co2 = float(qs.get("min_co2", ["0.0"])[0])
        max_hull = float(qs.get("max_hull", ["0.5"])[0])
        if release_id not in store.partitions:
            return 404, {"Content-Type": "application/json"}, {"error": "release not found"}
        rows = store.query_candidates(
            release_id=release_id,
            viewer_org=viewer_org,
            min_co2_uptake=min_co2,
            max_hull_energy=max_hull,
        )
        etag = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:16]
        return 200, {"Content-Type": "application/json", "ETag": etag}, {"release_id": release_id, "count": len(rows), "candidates": rows}

    if method == "GET" and path.startswith("/api/v1/lineage/"):
        release_id = path.split("/api/v1/lineage/", 1)[1]
        chain = store.lineage_chain(release_id)
        if not chain:
            return 404, {"Content-Type": "application/json"}, {"error": "lineage not found"}
        return 200, {"Content-Type": "application/json"}, {"release_id": release_id, "lineage": chain}

    return 404, {"Content-Type": "application/json"}, {"error": "route not found"}
