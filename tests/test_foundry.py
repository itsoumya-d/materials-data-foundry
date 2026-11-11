from __future__ import annotations

import hashlib
import json

import pytest

from foundry import (
    CandidateRecord,
    ContentAddressedDagRunner,
    MaterialsDualStore,
    dispatch_request,
)


def _sample_records() -> list[CandidateRecord]:
    return [
        CandidateRecord(
            candidate_id="mat-001",
            formula="Zn4O(BDC)3",
            spacegroup="Fm-3m",
            tenant_org="public",
            classification="PUBLIC",
            bandgap_ev=3.42,
            co2_uptake_mmol_g=4.85,
            hull_energy_ev=0.02,
            synthesizability_score=0.91,
        ),
        CandidateRecord(
            candidate_id="mat-002",
            formula="Cu3(BTC)2-LiX",
            spacegroup="Pm-3m",
            tenant_org="partner-chemco",
            classification="PROPRIETARY_PARTNER",
            bandgap_ev=2.15,
            co2_uptake_mmol_g=6.12,
            hull_energy_ev=0.04,
            synthesizability_score=0.84,
        ),
        CandidateRecord(
            candidate_id="mat-003",
            formula="Zr6O4(OH)4-F4",
            spacegroup="Ia-3d",
            tenant_org="public",
            classification="PUBLIC",
            bandgap_ev=3.95,
            co2_uptake_mmol_g=1.40,
            hull_energy_ev=0.38,
            synthesizability_score=0.62,
        ),
    ]


def test_dual_store_writes_relational_governance_and_columnar_checksum() -> None:
    store = MaterialsDualStore()
    records = _sample_records()
    part = store.write_columnar_release(
        release_id="rel-2026-11-v1",
        parent_release_id=None,
        dag_node_hash="sha256:node-aaa",
        created_by_org="public",
        records=records,
    )

    assert part.row_count == 3
    rel_row = store.conn.execute(
        "SELECT row_count, partition_checksum FROM dataset_releases WHERE release_id = ?",
        ("rel-2026-11-v1",),
    ).fetchone()
    assert rel_row["row_count"] == 3
    assert rel_row["partition_checksum"] == part.checksum()

    gov_rows = store.conn.execute(
        "SELECT candidate_id, tenant_org, classification, provenance_hash FROM candidate_governance ORDER BY candidate_id"
    ).fetchall()
    assert len(gov_rows) == 3
    expected_hash = hashlib.sha256(b"rel-2026-11-v1:mat-002:Cu3(BTC)2-LiX").hexdigest()
    assert gov_rows[1]["provenance_hash"] == expected_hash


def test_columnar_predicate_pushdown_and_tenant_redaction() -> None:
    store = MaterialsDualStore()
    store.write_columnar_release(
        release_id="rel-v1",
        parent_release_id=None,
        dag_node_hash="hash-1",
        created_by_org="public",
        records=_sample_records(),
    )

    # External viewer receives proprietary record with masked formula/spacegroup
    public_rows = store.query_candidates(
        release_id="rel-v1",
        viewer_org="academic-lab",
        min_co2_uptake=4.0,
        max_hull_energy=0.10,
    )
    assert [r["candidate_id"] for r in public_rows] == ["mat-001", "mat-002"]
    assert public_rows[0]["redacted"] is False
    assert public_rows[0]["formula"] == "Zn4O(BDC)3"
    assert public_rows[1]["redacted"] is True
    assert public_rows[1]["formula"] == "[REDACTED_PROPRIETARY]"
    assert public_rows[1]["spacegroup"] == "[REDACTED]"

    # Owning partner sees unredacted formula
    partner_rows = store.query_candidates(
        release_id="rel-v1",
        viewer_org="partner-chemco",
        min_co2_uptake=4.0,
        max_hull_energy=0.10,
    )
    assert partner_rows[1]["redacted"] is False
    assert partner_rows[1]["formula"] == "Cu3(BTC)2-LiX"

    # Strict non-redacting export drops foreign proprietary rows completely
    strict_rows = store.query_candidates(
        release_id="rel-v1",
        viewer_org="academic-lab",
        min_co2_uptake=4.0,
        max_hull_energy=0.10,
        redact_proprietary_formulas=False,
    )
    assert [r["candidate_id"] for r in strict_rows] == ["mat-001"]


def test_lineage_chain_preserves_chronological_release_ancestry() -> None:
    store = MaterialsDualStore()
    recs = _sample_records()
    store.write_columnar_release("rel-base", None, "h0", "public", recs[:1])
    store.write_columnar_release("rel-dft", "rel-base", "h1", "public", recs[:2])
    store.write_columnar_release("rel-curated", "rel-dft", "h2", "partner-chemco", recs)

    chain = store.lineage_chain("rel-curated")
    assert [c["release_id"] for c in chain] == ["rel-base", "rel-dft", "rel-curated"]
    assert [c["row_count"] for c in chain] == [1, 2, 3]


def test_content_addressed_dag_caching_and_schema_bump_invalidation() -> None:
    calls: dict[str, int] = {"ingest": 0, "relax": 0, "rank": 0}
    runner = ContentAddressedDagRunner()

    def ingest_fn(_deps: dict, params: dict) -> list[str]:
        calls["ingest"] += 1
        return [f"cif:{params['cohort']}:01", f"cif:{params['cohort']}:02"]

    def relax_fn(deps: dict, _params: dict) -> list[str]:
        calls["relax"] += 1
        return [x + ":relaxed" for x in deps["ingest"]]

    def rank_fn(deps: dict, _params: dict) -> int:
        calls["rank"] += 1
        return len(deps["relax"])

    runner.register("rank", ["relax"], "v1", rank_fn)
    runner.register("relax", ["ingest"], "v1", relax_fn)
    runner.register("ingest", [], "v1", ingest_fn)

    first = runner.materialize({"cohort": "mof-dac"})
    assert first.executed_nodes == ["ingest", "relax", "rank"]
    assert first.cached_nodes == []
    assert first.outputs["rank"] == 2

    # Identical params hit cache cleanly for every node
    second = runner.materialize({"cohort": "mof-dac"})
    assert second.executed_nodes == []
    assert second.cached_nodes == ["ingest", "relax", "rank"]
    assert calls == {"ingest": 1, "relax": 1, "rank": 1}

    # Schema bump on downstream transform keeps upstream ingest cached
    runner.register("relax", ["ingest"], "v2", relax_fn)
    third = runner.materialize({"cohort": "mof-dac"})
    assert third.cached_nodes == ["ingest", "rank"] or third.cached_nodes == ["ingest"]
    assert "ingest" in third.cached_nodes
    assert "relax" in third.executed_nodes


def test_dag_runner_detects_cycles() -> None:
    runner = ContentAddressedDagRunner()
    runner.register("a", ["b"], "v1", lambda _d, _p: 1)
    runner.register("b", ["a"], "v1", lambda _d, _p: 2)
    with pytest.raises(ValueError, match="Cycle detected"):
        runner.materialize({})


def test_http_api_dispatch_routes_and_etag() -> None:
    store = MaterialsDualStore()
    store.write_columnar_release("rel-api-1", None, "h-api", "public", _sample_records())

    status, headers, body = dispatch_request(
        store,
        "GET",
        "/api/v1/candidates",
        "release_id=rel-api-1&viewer_org=partner-chemco&min_co2=4.5&max_hull=0.1",
    )
    assert status == 200
    assert "ETag" in headers
    assert body["count"] == 2
    expected_etag = hashlib.sha256(
        json.dumps(body["candidates"], sort_keys=True).encode()
    ).hexdigest()[:16]
    assert headers["ETag"] == expected_etag

    status_lin, _, body_lin = dispatch_request(store, "GET", "/api/v1/lineage/rel-api-1")
    assert status_lin == 200
    assert len(body_lin["lineage"]) == 1

    status_404, _, _ = dispatch_request(store, "GET", "/api/v1/candidates", "release_id=missing")
    assert status_404 == 404

    status_bad, _, _ = dispatch_request(store, "POST", "/api/v1/unknown")
    assert status_bad == 404
