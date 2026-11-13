import type { Defect } from "./api";

/** The case the guided demo walks through: a third-party agent (τ-bench airline, unmodified) writing
 *  to its database after the user's confirmation had lapsed, then passing on the fixed version.
 *  Falls back to any real-write defect, so the demo works on whatever evidence this machine has. */
export const FEATURED_DEFECT = "tau-airline:v1:T10-baggage-yes-then-more";

export function pickFeatured(defects: Defect[]): Defect | null {
  return (
    defects.find((d) => d.id === FEATURED_DEFECT) ??
    defects.find((d) => d.kind === "side_effect" && d.status === "fixed_verified") ??
    defects.find((d) => d.kind === "side_effect") ??
    null
  );
}
