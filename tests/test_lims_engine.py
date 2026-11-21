"""Unit tests for LIMS Database Administration & ISO/IEC 17025 Compliance Engine."""

import os
import tempfile
import time
from foundry.lims_engine import (
    CustomerProfile,
    LIMSDatabaseManager,
    SampleRegistration,
    TestResultEntry,
    TestSpecification,
)


def test_customer_and_specification_registration():
    mgr = LIMSDatabaseManager(":memory:")
    
    # 1. Customer Registration
    cust = CustomerProfile(
        customer_id="NZ-EXP-088",
        company_name="Aotearoa Dairy Exporters Ltd",
        export_market="China (GACC)",
        contact_email="qa@aotearoadairy.co.nz",
        created_at=time.time()
    )
    mgr.register_customer(cust)

    # 2. Specification Configuration
    spec_moisture = TestSpecification(
        spec_id="SPEC-MILK-MOISTURE",
        product_category="Dairy Infant Formula",
        method_code="GB5009.3-2016",
        parameter_name="Moisture Content",
        unit="g/100g",
        min_limit=None,
        max_limit=4.0,
        regulatory_standard="GB 10765-2021"
    )
    spec_protein = TestSpecification(
        spec_id="SPEC-MILK-PROTEIN",
        product_category="Dairy Infant Formula",
        method_code="GB5009.5-2016",
        parameter_name="Crude Protein",
        unit="g/100g",
        min_limit=11.5,
        max_limit=14.5,
        regulatory_standard="GB 10765-2021"
    )
    mgr.define_specification(spec_moisture)
    mgr.define_specification(spec_protein)

    valid, count = mgr.verify_audit_trail_integrity()
    assert valid is True
    assert count == 3  # 1 customer + 2 specs


def test_sample_accessioning_and_analytical_testing():
    mgr = LIMSDatabaseManager(":memory:")
    
    cust = CustomerProfile(
        customer_id="NZ-HONEY-01",
        company_name="Waikato Apiaries Global",
        export_market="China",
        contact_email="export@waikatoapiaries.co.nz"
    )
    mgr.register_customer(cust)

    spec = TestSpecification(
        spec_id="SPEC-HONEY-MGO",
        product_category="Manuka Honey",
        method_code="NZ-MGO-HPLC",
        parameter_name="Methylglyoxal (MGO)",
        unit="mg/kg",
        min_limit=250.0,
        max_limit=None,
        regulatory_standard="MPI Manuka Standard & GB 14963"
    )
    mgr.define_specification(spec)

    sample = SampleRegistration(
        sample_id="SMP-2026-9041",
        customer_id="NZ-HONEY-01",
        product_category="Manuka Honey",
        batch_lot="LOT-MGO-8849",
        registered_at=time.time(),
        status="REGISTERED"
    )
    mgr.register_sample(sample)

    # Test Compliant Result
    res = mgr.record_analytical_result(
        TestResultEntry(
            sample_id="SMP-2026-9041",
            method_code="NZ-MGO-HPLC",
            measured_value=310.5,
            technician_id="TECH-HAMILTON-04",
            timestamp=time.time(),
            uncertainty=2.5
        ),
        actor_id="ANALYST_SOU"
    )
    assert res["is_compliant"] is True
    assert res["discrepancy"] is None

    # Verify Export Certificate Generation
    cert = mgr.generate_export_certificate("SMP-2026-9041")
    assert cert["sample"]["final_status"] == "APPROVED_FOR_EXPORT"
    assert len(cert["analytical_test_matrix"]) == 1
    assert cert["analytical_test_matrix"][0]["compliant"] is True
    assert "digital_signature_digest" in cert


def test_discrepancy_detection_and_rejection():
    mgr = LIMSDatabaseManager(":memory:")
    
    cust = CustomerProfile(
        customer_id="NZ-MEAT-02",
        company_name="Ruakura Prime Meats",
        export_market="China",
        contact_email="qa@ruakuraprime.co.nz"
    )
    mgr.register_customer(cust)

    spec = TestSpecification(
        spec_id="SPEC-MEAT-TEMP",
        product_category="Chilled Prime Beef",
        method_code="TEMP-SENSOR-01",
        parameter_name="Core Temperature",
        unit="°C",
        min_limit=-0.5,
        max_limit=4.0,
        regulatory_standard="GB 2707-2016"
    )
    mgr.define_specification(spec)

    sample = SampleRegistration(
        sample_id="SMP-MEAT-5501",
        customer_id="NZ-MEAT-02",
        product_category="Chilled Prime Beef",
        batch_lot="LOT-CHILLED-009",
        registered_at=time.time(),
        status="REGISTERED"
    )
    mgr.register_sample(sample)

    # Non-compliant result (exceeds 4.0 °C)
    res = mgr.record_analytical_result(
        TestResultEntry(
            sample_id="SMP-MEAT-5501",
            method_code="TEMP-SENSOR-01",
            measured_value=5.8,
            technician_id="TECH-WAIKATO-11",
            timestamp=time.time(),
            uncertainty=0.1
        ),
        actor_id="ANALYST_SOU"
    )
    assert res["is_compliant"] is False
    assert "exceeds maximum threshold" in res["discrepancy"]

    cert = mgr.generate_export_certificate("SMP-MEAT-5501")
    assert cert["sample"]["final_status"] == "REJECTED_NON_COMPLIANT"
    assert cert["analytical_test_matrix"][0]["compliant"] is False


def test_iso17025_cryptographic_audit_trail_tamper_detection():
    mgr = LIMSDatabaseManager(":memory:")
    
    cust = CustomerProfile(
        customer_id="NZ-CUST-99",
        company_name="Test Enterprise Ltd",
        export_market="China",
        contact_email="test@enterprise.co.nz"
    )
    mgr.register_customer(cust)

    valid, count = mgr.verify_audit_trail_integrity()
    assert valid is True
    assert count == 1

    # Simulate malicious database tampering on audit log record
    with mgr.conn:
        mgr.conn.execute("UPDATE iso17025_audit_log SET actor_id = 'MALICIOUS_IMPOSTER' WHERE log_id = 1")

    valid_after_tamper, bad_id = mgr.verify_audit_trail_integrity()
    assert valid_after_tamper is False
    assert bad_id == 1


def test_backup_and_recovery_verification():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = os.path.join(tmpdir, "primary_lims.db")
        mgr = LIMSDatabaseManager(db_file)
        
        cust = CustomerProfile(
            customer_id="NZ-BACKUP-01",
            company_name="Backup Verification Corp",
            export_market="China",
            contact_email="ops@backup.co.nz"
        )
        mgr.register_customer(cust)

        backup_dir = os.path.join(tmpdir, "backups")
        backup_path = mgr.backup_database(backup_dir)

        assert os.path.exists(backup_path)
        sha_file = backup_path.replace(".db", ".sha256")
        assert os.path.exists(sha_file)

        # Verify restored database
        restored_mgr = LIMSDatabaseManager(backup_path)
        restored_cust = restored_mgr.conn.execute("SELECT * FROM customer_profiles WHERE customer_id = 'NZ-BACKUP-01'").fetchone()
        assert restored_cust is not None
        assert restored_cust["company_name"] == "Backup Verification Corp"
