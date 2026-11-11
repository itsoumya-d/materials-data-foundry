export interface CrystalCandidate {
  candidateId: string;
  formula: string;
  co2UptakeMmolG: number;
  hullEnergyEv: number;
  synthesizabilityScore: number;
  redacted: boolean;
}

export interface RankedCandidate extends CrystalCandidate {
  paretoOptimal: boolean;
  compositeScore: number;
}

/**
 * Computes the non-dominated Pareto frontier maximizing CO2 uptake and synthesizability
 * while minimizing thermodynamic energy above the convex hull.
 */
export function rankParetoCandidates(
  candidates: CrystalCandidate[],
  weights: { uptake: number; stability: number; synth: number } = {
    uptake: 0.5,
    stability: 0.3,
    synth: 0.2,
  }
): RankedCandidate[] {
  const isDominated = (a: CrystalCandidate, b: CrystalCandidate): boolean => {
    const bNoWorse =
      b.co2UptakeMmolG >= a.co2UptakeMmolG &&
      b.synthesizabilityScore >= a.synthesizabilityScore &&
      b.hullEnergyEv <= a.hullEnergyEv;
    const bStrictlyBetter =
      b.co2UptakeMmolG > a.co2UptakeMmolG ||
      b.synthesizabilityScore > a.synthesizabilityScore ||
      b.hullEnergyEv < a.hullEnergyEv;
    return bNoWorse && bStrictlyBetter;
  };

  return candidates
    .map((cand) => {
      const dominated = candidates.some(
        (other) => other.candidateId !== cand.candidateId && isDominated(cand, other)
      );
      const stabilityTerm = Math.max(0, 1 - cand.hullEnergyEv * 2);
      const compositeScore = Number(
        (
          weights.uptake * (cand.co2UptakeMmolG / 10) +
          weights.stability * stabilityTerm +
          weights.synth * cand.synthesizabilityScore
        ).toFixed(4)
      );
      return {
        ...cand,
        paretoOptimal: !dominated,
        compositeScore,
      };
    })
    .sort((x, y) => {
      if (x.paretoOptimal !== y.paretoOptimal) return x.paretoOptimal ? -1 : 1;
      return y.compositeScore - x.compositeScore;
    });
}

export function exportGovernanceSafeCsv(rows: RankedCandidate[]): string {
  const header = "candidate_id,formula,co2_uptake_mmol_g,hull_energy_ev,synthesizability,pareto_optimal,composite_score";
  const lines = rows.map(
    (r) =>
      `${r.candidateId},"${r.formula.replace(/"/g, '""')}",${r.co2UptakeMmolG},${r.hullEnergyEv},${r.synthesizabilityScore},${r.paretoOptimal},${r.compositeScore}`
  );
  return [header, ...lines].join("\n");
}
