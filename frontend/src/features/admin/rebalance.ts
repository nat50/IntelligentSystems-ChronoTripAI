import type { OptimizerSettings } from "@/lib/types";

type Objective = OptimizerSettings["objective"];
export type Weight = keyof Objective;
const KEYS: Weight[] = ["popularity", "golden", "travel"];

/** D4 sliders: moving one weight rescales the other two so the three still sum to 1 (2 decimals) */
export function rebalance(o: Objective, key: Weight, value: number): Objective {
  const [a, b] = KEYS.filter((k) => k !== key);
  const rest = o[a] + o[b];
  const left = Math.round((1 - value) * 100) / 100;
  const na = Math.round((rest > 0 ? (o[a] / rest) * left : left / 2) * 100) / 100;
  // the last weight takes the rounding error, so the sum is exactly 1
  return { ...o, [key]: value, [a]: na, [b]: Math.round((left - na) * 100) / 100 };
}
