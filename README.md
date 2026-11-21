# materials-data-foundry

Multi-paradigm scientific data & asset orchestration platform for computational materials discovery:

- **Dual-Store Architecture (`foundry/dual_store.py`)**: ACID SQLite/PostgreSQL-compatible provenance catalog (`dataset_releases`, `candidate_governance`) paired with vectorized columnar partitions supporting predicate pushdown and per-tenant redaction (`[REDACTED_PROPRIETARY]`) before HTTP/CSV serialization.
- **Content-Addressed Asset DAG (`foundry/lineage_dag.py`)**: Dagster/Flyte-inspired topological materializer with SHA-256 `(node, schema_version, upstream_deps, params)` memoization, selective invalidation on schema bumps, and cycle guards.
- **Scientist Query & Lineage Router (`foundry/api.py`)**: Framework-agnostic API exposing `/api/v1/candidates` with `ETag` digest headers and `/api/v1/lineage/{release_id}` ancestry chains.
- **LIMS Database Administration & ISO/IEC 17025 Audit Engine (`foundry/lims_engine.py`)**: Relational laboratory information management system schema, sample accessioning, regulatory limit verification, automated export certificate generation, and cryptographic SHA-256 hash-chained audit trails meeting ISO/IEC 17025, IANZ, and CNAS compliance standards.
- **TypeScript Pareto Explorer (`web/src/paretoExplorer.ts`)**: Non-dominated multi-objective ranking across CO2 uptake, convex hull stability, and synthesizability plus governance-safe CSV export.
- **Container & K8s Manifests (`deploy/`)**: Worker image and Kubernetes batch Job spec for materialization pipelines.

## Local Verification

```bash
pytest -v
cd web && npm install && npm run build && npm test
```
