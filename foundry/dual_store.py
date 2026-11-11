"""Dual-paradigm storage engine for computational materials discovery:
1. Relational SQLite/PostgreSQL-compatible governance & provenance catalog (experiment runs, partner ACLs, dataset lineage).
2. Columnar vectorized metric partition store (predicate pushdown + column projection for crystal candidates).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CandidateRecord:
    candidate_id: str
    formula: str
    spacegroup: str
    tenant_org: str
    classification: str  # "PUBLIC" | "PROPRIETARY_PARTNER"
    bandgap_ev: float
    co2_uptake_mmol_g: float
    hull_energy_ev: float
    synthesizability_score: float


@dataclass(frozen=True)
class ColumnarPartition:
    partition_key: str
    schema_version: str
    candidate_ids: list[str]
    formulas: list[str]
    spacegroups: list[str]
    tenant_orgs: list[str]
    classifications: list[str]
    bandgap_ev: list[float]
    co2_uptake_mmol_g: list[float]
    hull_energy_ev: list[float]
    synthesizability_score: list[float]

    @property
    def row_count(self) -> int:
        return len(self.candidate_ids)

    def checksum(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class MaterialsDualStore:
    """Combines ACID relational governance metadata with columnar analytical partitions."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.partitions: dict[str, ColumnarPartition] = {}
        self._init_relational_schema()

    def _init_relational_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS dataset_releases (
                release_id TEXT PRIMARY KEY,
                parent_release_id TEXT,
                dag_node_hash TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                partition_checksum TEXT NOT NULL,
                created_by_org TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS candidate_governance (
                candidate_id TEXT NOT NULL,
                release_id TEXT NOT NULL REFERENCES dataset_releases(release_id),
                tenant_org TEXT NOT NULL,
                classification TEXT NOT NULL CHECK (classification IN ('PUBLIC', 'PROPRIETARY_PARTNER')),
                provenance_hash TEXT NOT NULL,
                PRIMARY KEY (candidate_id, release_id)
            );

            CREATE INDEX IF NOT EXISTS idx_gov_tenant ON candidate_governance(tenant_org, classification);
            """
        )
        self.conn.commit()

    def write_columnar_release(
        self,
        release_id: str,
        parent_release_id: str | None,
        dag_node_hash: str,
        created_by_org: str,
        records: list[CandidateRecord],
    ) -> ColumnarPartition:
        part = ColumnarPartition(
            partition_key=release_id,
            schema_version="v2.materials.columnar",
            candidate_ids=[r.candidate_id for r in records],
            formulas=[r.formula for r in records],
            spacegroups=[r.spacegroup for r in records],
            tenant_orgs=[r.tenant_org for r in records],
            classifications=[r.classification for r in records],
            bandgap_ev=[r.bandgap_ev for r in records],
            co2_uptake_mmol_g=[r.co2_uptake_mmol_g for r in records],
            hull_energy_ev=[r.hull_energy_ev for r in records],
            synthesizability_score=[r.synthesizability_score for r in records],
        )
        self.partitions[release_id] = part
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO dataset_releases (release_id, parent_release_id, dag_node_hash, row_count, partition_checksum, created_by_org)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (release_id, parent_release_id, dag_node_hash, part.row_count, part.checksum(), created_by_org),
            )
            for rec in records:
                prov = hashlib.sha256(f"{release_id}:{rec.candidate_id}:{rec.formula}".encode()).hexdigest()
                self.conn.execute(
                    """
                    INSERT INTO candidate_governance (candidate_id, release_id, tenant_org, classification, provenance_hash)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (rec.candidate_id, release_id, rec.tenant_org, rec.classification, prov),
                )
        return part

    def query_candidates(
        self,
        release_id: str,
        viewer_org: str,
        min_co2_uptake: float = 0.0,
        max_hull_energy: float = 1.0,
        redact_proprietary_formulas: bool = True,
    ) -> list[dict[str, Any]]:
        part = self.partitions[release_id]
        results: list[dict[str, Any]] = []
        # Columnar predicate pushdown before row materialization
        for i in range(part.row_count):
            if part.co2_uptake_mmol_g[i] < min_co2_uptake:
                continue
            if part.hull_energy_ev[i] > max_hull_energy:
                continue
            owner = part.tenant_orgs[i]
            cls = part.classifications[i]
            if cls == "PROPRIETARY_PARTNER" and owner != viewer_org and not redact_proprietary_formulas:
                continue
            masked = cls == "PROPRIETARY_PARTNER" and owner != viewer_org
            results.append(
                {
                    "candidate_id": part.candidate_ids[i],
                    "formula": "[REDACTED_PROPRIETARY]" if masked else part.formulas[i],
                    "spacegroup": "[REDACTED]" if masked else part.spacegroups[i],
                    "co2_uptake_mmol_g": part.co2_uptake_mmol_g[i],
                    "hull_energy_ev": part.hull_energy_ev[i],
                    "bandgap_ev": part.bandgap_ev[i],
                    "synthesizability_score": part.synthesizability_score[i],
                    "redacted": masked,
                }
            )
        return results

    def lineage_chain(self, release_id: str) -> list[dict[str, Any]]:
        chain: list[dict[str, Any]] = []
        cur: str | None = release_id
        while cur is not None:
            row = self.conn.execute(
                "SELECT release_id, parent_release_id, dag_node_hash, row_count, partition_checksum FROM dataset_releases WHERE release_id = ?",
                (cur,),
            ).fetchone()
            if row is None:
                break
            chain.append(dict(row))
            cur = row["parent_release_id"]
        chain.reverse()
        return chain
