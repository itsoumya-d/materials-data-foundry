"""Dagster-style asset dependency DAG + Flyte-style content-addressed task memoization."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class AssetNode:
    name: str
    deps: list[str]
    schema_version: str
    fn: Callable[[dict[str, Any], dict[str, Any]], Any]


@dataclass
class MaterializationStats:
    executed_nodes: list[str] = field(default_factory=list)
    cached_nodes: list[str] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    cache_keys: dict[str, str] = field(default_factory=dict)


class ContentAddressedDagRunner:
    """Executes typed pipeline assets topologically while skipping deterministically cached transforms."""

    def __init__(self) -> None:
        self.nodes: dict[str, AssetNode] = {}
        self.cache: dict[str, Any] = {}

    def register(
        self,
        name: str,
        deps: list[str],
        schema_version: str,
        fn: Callable[[dict[str, Any], dict[str, Any]], Any],
    ) -> None:
        self.nodes[name] = AssetNode(name=name, deps=deps, schema_version=schema_version, fn=fn)

    def _topo_order(self) -> list[str]:
        visited: set[str] = set()
        visiting: set[str] = set()
        order: list[str] = []

        def dfs(n: str) -> None:
            if n in visiting:
                raise ValueError(f"Cycle detected in asset DAG at {n}")
            if n in visited:
                return
            visiting.add(n)
            for dep in self.nodes[n].deps:
                dfs(dep)
            visiting.remove(n)
            visited.add(n)
            order.append(n)

        for name in self.nodes:
            dfs(name)
        return order

    def materialize(self, params: dict[str, Any]) -> MaterializationStats:
        stats = MaterializationStats()
        for name in self._topo_order():
            node = self.nodes[name]
            dep_inputs = {d: stats.outputs[d] for d in node.deps}
            digest_src = json.dumps(
                {"node": name, "schema": node.schema_version, "deps": dep_inputs, "params": params},
                sort_keys=True,
                default=str,
            ).encode("utf-8")
            cache_key = hashlib.sha256(digest_src).hexdigest()
            stats.cache_keys[name] = cache_key

            if cache_key in self.cache:
                stats.cached_nodes.append(name)
                stats.outputs[name] = self.cache[cache_key]
            else:
                out = node.fn(dep_inputs, params)
                self.cache[cache_key] = out
                stats.executed_nodes.append(name)
                stats.outputs[name] = out
        return stats
