import test from "node:test";
import assert from "node:assert/strict";
import { exportGovernanceSafeCsv, rankParetoCandidates, type CrystalCandidate } from "../src/paretoExplorer.ts";

test("rankParetoCandidates isolates non-dominated crystal structures", () => {
  const input: CrystalCandidate[] = [
    {
      candidateId: "c1",
      formula: "Zn4O(BDC)3",
      co2UptakeMmolG: 4.8,
      hullEnergyEv: 0.02,
      synthesizabilityScore: 0.9,
      redacted: false,
    },
    {
      candidateId: "c2",
      formula: "[REDACTED_PROPRIETARY]",
      co2UptakeMmolG: 6.1,
      hullEnergyEv: 0.05,
      synthesizabilityScore: 0.85,
      redacted: true,
    },
    {
      candidateId: "c3",
      formula: "Zr6O4-suboptimal",
      co2UptakeMmolG: 3.1,
      hullEnergyEv: 0.12,
      synthesizabilityScore: 0.72,
      redacted: false,
    },
  ];

  const ranked = rankParetoCandidates(input);
  const byId = Object.fromEntries(ranked.map((r) => [r.candidateId, r]));

  assert.equal(byId.c1.paretoOptimal, true);
  assert.equal(byId.c2.paretoOptimal, true);
  assert.equal(byId.c3.paretoOptimal, false);
  assert.equal(ranked[ranked.length - 1].candidateId, "c3");

  const csv = exportGovernanceSafeCsv(ranked);
  assert.match(csv, /\[REDACTED_PROPRIETARY\]/);
  assert.equal(csv.split("\n").length, 4);
});
