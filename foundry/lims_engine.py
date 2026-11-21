"""LIMS Database Administration & ISO/IEC 17025 Audit Engine.

Provides relational schema management, sample registration, regulatory testing threshold
verification, automated export compliance reporting, and immutable cryptographic audit trails
for accredited analytical laboratories (ISO/IEC 17025 / IANZ / CNAS).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class CustomerProfile:
    customer_id: str
    company_name: str
    export_market: str
    contact_email: str
    created_at: float = 0.0


@dataclass(frozen=True)
class TestSpecification:
    __test__ = False
    spec_id: str
    product_category: str
    method_code: str
    parameter_name: str
    unit: str
    min_limit: Optional[float]
    max_limit: Optional[float]
    regulatory_standard: str  # e.g., "GB 10765-2021", "ISO 17025"


@dataclass(frozen=True)
class SampleRegistration:
    sample_id: str
    customer_id: str
    product_category: str
    batch_lot: str
    registered_at: float
    status: str  # "REGISTERED", "TESTING", "VERIFIED", "CERTIFIED", "REJECTED"


@dataclass(frozen=True)
class TestResultEntry:
    __test__ = False
    sample_id: str
    method_code: str
    measured_value: float
    technician_id: str
    timestamp: float
    uncertainty: float = 0.01


class LIMSDatabaseManager:
    """Production Laboratory Information Management System Database Administrator & Compliance Engine."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._last_audit_hash = "GENESIS_AUDIT_BLOCK_00000000"
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize normalized relational tables with integrity constraints."""
        with self.conn:
            # 1. Customer Profiles
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS customer_profiles (
                    customer_id TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    export_market TEXT NOT NULL,
                    contact_email TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            """)

            # 2. Test Specifications & Regulatory Limits
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS test_specifications (
                    spec_id TEXT PRIMARY KEY,
                    product_category TEXT NOT NULL,
                    method_code TEXT NOT NULL,
                    parameter_name TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    min_limit REAL,
                    max_limit REAL,
                    regulatory_standard TEXT NOT NULL,
                    UNIQUE(product_category, method_code)
                )
            """)

            # 3. Sample Registrations
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS sample_registrations (
                    sample_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    product_category TEXT NOT NULL,
                    batch_lot TEXT NOT NULL,
                    registered_at REAL NOT NULL,
                    status TEXT NOT NULL,
                    FOREIGN KEY(customer_id) REFERENCES customer_profiles(customer_id)
                )
            """)

            # 4. Analytical Test Results
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS analytical_results (
                    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sample_id TEXT NOT NULL,
                    method_code TEXT NOT NULL,
                    measured_value REAL NOT NULL,
                    uncertainty REAL NOT NULL,
                    technician_id TEXT NOT NULL,
                    is_compliant INTEGER NOT NULL,
                    discrepancy_note TEXT,
                    timestamp REAL NOT NULL,
                    FOREIGN KEY(sample_id) REFERENCES sample_registrations(sample_id)
                )
            """)

            # 5. ISO/IEC 17025 Immutable Audit Log (Chained Hashes)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS iso17025_audit_log (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    record_hash TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
            """)

            # Performance Indexes for High-Volume Laboratory Queries
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_customer ON sample_registrations(customer_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_results_sample ON analytical_results(sample_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_spec_category ON test_specifications(product_category)")

    def _log_audit_event(self, event_type: str, table_name: str, record_id: str, actor_id: str, details: Dict[str, Any]) -> str:
        """Append an immutable cryptographically-chained audit record adhering to ISO/IEC 17025 §7.11."""
        now = time.time()
        details_str = json.dumps(details, sort_keys=True)
        raw_payload = f"{self._last_audit_hash}:{event_type}:{table_name}:{record_id}:{actor_id}:{details_str}:{now}"
        record_hash = hashlib.sha256(raw_payload.encode()).hexdigest()

        with self.conn:
            self.conn.execute("""
                INSERT INTO iso17025_audit_log (event_type, table_name, record_id, actor_id, details_json, prev_hash, record_hash, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (event_type, table_name, record_id, actor_id, details_str, self._last_audit_hash, record_hash, now))

        self._last_audit_hash = record_hash
        return record_hash

    def register_customer(self, customer: CustomerProfile, actor_id: str = "SYS_ADMIN") -> None:
        """Register or update customer account with audit trail."""
        created_at = customer.created_at or time.time()
        with self.conn:
            self.conn.execute("""
                INSERT OR REPLACE INTO customer_profiles (customer_id, company_name, export_market, contact_email, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (customer.customer_id, customer.company_name, customer.export_market, customer.contact_email, created_at))
        self._log_audit_event("CUSTOMER_PROFILE_UPDATE", "customer_profiles", customer.customer_id, actor_id, asdict(customer))

    def define_specification(self, spec: TestSpecification, actor_id: str = "QA_MANAGER") -> None:
        """Configure accredited test parameters, measurement units, and threshold ranges."""
        with self.conn:
            self.conn.execute("""
                INSERT OR REPLACE INTO test_specifications (spec_id, product_category, method_code, parameter_name, unit, min_limit, max_limit, regulatory_standard)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (spec.spec_id, spec.product_category, spec.method_code, spec.parameter_name, spec.unit, spec.min_limit, spec.max_limit, spec.regulatory_standard))
        self._log_audit_event("SPECIFICATION_UPDATE", "test_specifications", spec.spec_id, actor_id, asdict(spec))

    def register_sample(self, sample: SampleRegistration, actor_id: str = "SAMPLE_RECEIVING") -> None:
        """Register newly accessioned food export sample into the LIMS."""
        with self.conn:
            self.conn.execute("""
                INSERT INTO sample_registrations (sample_id, customer_id, product_category, batch_lot, registered_at, status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (sample.sample_id, sample.customer_id, sample.product_category, sample.batch_lot, sample.registered_at, sample.status))
        self._log_audit_event("SAMPLE_ACCESSIONED", "sample_registrations", sample.sample_id, actor_id, asdict(sample))

    def record_analytical_result(self, entry: TestResultEntry, actor_id: str) -> Dict[str, Any]:
        """Record test result, automatically evaluate against specification limits, and log discrepancies."""
        # 1. Fetch matching specification
        spec_row = self.conn.execute("""
            SELECT s.product_category, ts.min_limit, ts.max_limit, ts.parameter_name, ts.unit, ts.regulatory_standard
            FROM sample_registrations s
            JOIN test_specifications ts ON ts.product_category = s.product_category
            WHERE s.sample_id = ? AND ts.method_code = ?
        """, (entry.sample_id, entry.method_code)).fetchone()

        if not spec_row:
            raise ValueError(f"No specification found for sample {entry.sample_id} and method {entry.method_code}")

        min_lim = spec_row["min_limit"]
        max_lim = spec_row["max_limit"]
        val = entry.measured_value

        is_compliant = 1
        discrepancy = None

        if min_lim is not None and val < min_lim:
            is_compliant = 0
            discrepancy = f"Result {val} below minimum tolerance {min_lim} {spec_row['unit']}"
        elif max_lim is not None and val > max_lim:
            is_compliant = 0
            discrepancy = f"Result {val} exceeds maximum threshold {max_lim} {spec_row['unit']}"

        with self.conn:
            self.conn.execute("""
                INSERT INTO analytical_results (sample_id, method_code, measured_value, uncertainty, technician_id, is_compliant, discrepancy_note, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (entry.sample_id, entry.method_code, entry.measured_value, entry.uncertainty, entry.technician_id, is_compliant, discrepancy, entry.timestamp))

            # Update sample status
            new_status = "VERIFIED" if is_compliant else "REJECTED"
            self.conn.execute("UPDATE sample_registrations SET status = ? WHERE sample_id = ?", (new_status, entry.sample_id))

        event_details = {
            "method_code": entry.method_code,
            "measured_value": entry.measured_value,
            "uncertainty": entry.uncertainty,
            "is_compliant": bool(is_compliant),
            "discrepancy": discrepancy,
            "regulatory_standard": spec_row["regulatory_standard"]
        }
        self._log_audit_event("ANALYTICAL_RESULT_LOGGED", "analytical_results", entry.sample_id, actor_id, event_details)

        return {
            "sample_id": entry.sample_id,
            "method_code": entry.method_code,
            "is_compliant": bool(is_compliant),
            "discrepancy": discrepancy
        }

    def generate_export_certificate(self, sample_id: str) -> Dict[str, Any]:
        """Automated routine reporting pipeline generating verified compliance export certificates."""
        sample = self.conn.execute("""
            SELECT s.sample_id, s.product_category, s.batch_lot, s.registered_at, s.status,
                   c.company_name, c.export_market, c.customer_id
            FROM sample_registrations s
            JOIN customer_profiles c ON s.customer_id = c.customer_id
            WHERE s.sample_id = ?
        """, (sample_id,)).fetchone()

        if not sample:
            raise KeyError(f"Sample {sample_id} not found")

        results = self.conn.execute("""
            SELECT r.method_code, r.measured_value, r.uncertainty, r.is_compliant, r.discrepancy_note,
                   ts.parameter_name, ts.unit, ts.regulatory_standard
            FROM analytical_results r
            JOIN test_specifications ts ON r.method_code = ts.method_code
            WHERE r.sample_id = ?
        """, (sample_id,)).fetchall()

        all_compliant = all(r["is_compliant"] == 1 for r in results) if results else False

        cert_data = {
            "certificate_id": f"CERT-{sample_id}-{int(time.time())}",
            "customer": {
                "id": sample["customer_id"],
                "name": sample["company_name"],
                "export_market": sample["export_market"]
            },
            "sample": {
                "id": sample["sample_id"],
                "category": sample["product_category"],
                "batch_lot": sample["batch_lot"],
                "accession_date": sample["registered_at"],
                "final_status": "APPROVED_FOR_EXPORT" if all_compliant else "REJECTED_NON_COMPLIANT"
            },
            "analytical_test_matrix": [
                {
                    "method": r["method_code"],
                    "parameter": r["parameter_name"],
                    "result": f"{r['measured_value']} ± {r['uncertainty']} {r['unit']}",
                    "compliant": bool(r["is_compliant"]),
                    "standard": r["regulatory_standard"],
                    "discrepancy": r["discrepancy_note"]
                }
                for r in results
            ],
            "iso17025_accreditation": "IANZ / CNAS Pre-Shipment Laboratory Verification",
            "issued_at": time.time()
        }

        # Calculate tamper-evident hash
        cert_hash = hashlib.sha256(json.dumps(cert_data, sort_keys=True).encode()).hexdigest()
        cert_data["digital_signature_digest"] = cert_hash

        return cert_data

    def verify_audit_trail_integrity(self) -> Tuple[bool, int]:
        """Verify the cryptographic hash-chain integrity of the ISO/IEC 17025 audit trail."""
        rows = self.conn.execute("""
            SELECT log_id, event_type, table_name, record_id, actor_id, details_json, prev_hash, record_hash, timestamp
            FROM iso17025_audit_log ORDER BY log_id ASC
        """).fetchall()

        current_prev = "GENESIS_AUDIT_BLOCK_00000000"
        for row in rows:
            if row["prev_hash"] != current_prev:
                return False, row["log_id"]

            raw_payload = f"{row['prev_hash']}:{row['event_type']}:{row['table_name']}:{row['record_id']}:{row['actor_id']}:{row['details_json']}:{row['timestamp']}"
            expected_hash = hashlib.sha256(raw_payload.encode()).hexdigest()

            if row["record_hash"] != expected_hash:
                return False, row["log_id"]

            current_prev = row["record_hash"]

        return True, len(rows)

    def backup_database(self, destination_dir: str) -> str:
        """Perform reliable point-in-time database snapshot with SHA-256 verification checksum."""
        dest_path = Path(destination_dir)
        dest_path.mkdir(parents=True, exist_ok=True)
        backup_file = dest_path / f"lims_backup_{int(time.time())}.db"

        backup_conn = sqlite3.connect(str(backup_file))
        with backup_conn:
            self.conn.backup(backup_conn, pages=100)
        backup_conn.close()

        # Generate checksum of backup file
        hasher = hashlib.sha256()
        with open(backup_file, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        digest = hasher.hexdigest()

        checksum_file = backup_file.with_suffix(".sha256")
        checksum_file.write_text(digest)

        return str(backup_file)
