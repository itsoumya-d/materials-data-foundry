"""Materials Data Foundry: dual-store governance, content-addressed DAGs, and Pareto exploration."""

from .api import dispatch_request
from .dual_store import CandidateRecord, ColumnarPartition, MaterialsDualStore
from .lineage_dag import AssetNode, ContentAddressedDagRunner, MaterializationStats

__all__ = [
    "AssetNode",
    "CandidateRecord",
    "ColumnarPartition",
    "ContentAddressedDagRunner",
    "MaterializationStats",
    "MaterialsDualStore",
    "dispatch_request",
]
