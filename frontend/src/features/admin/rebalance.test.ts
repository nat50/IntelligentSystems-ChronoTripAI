// Run: node --test src/features/admin/rebalance.test.ts (Node 22.18+ strips the types)
import assert from "node:assert/strict";
import test from "node:test";
import { rebalance } from "./rebalance.ts";

const sum = (o: Record<string, number>) => Math.round(Object.values(o).reduce((a, b) => a + b, 0) * 100) / 100;

test("keeps the proportions of the other two weights and sums to 1", () => {
  const out = rebalance({ popularity: 0.6, golden: 0.3, travel: 0.1 }, "popularity", 0.2);
  assert.deepEqual(out, { popularity: 0.2, golden: 0.6, travel: 0.2 });
});

test("splits evenly when the other two are zero", () => {
  assert.deepEqual(rebalance({ popularity: 1, golden: 0, travel: 0 }, "popularity", 0.5), { popularity: 0.5, golden: 0.25, travel: 0.25 });
});

test("always sums to exactly 1 on the slider steps", () => {
  let o = { popularity: 0.6, golden: 0.3, travel: 0.1 };
  for (const key of ["golden", "travel", "popularity", "travel"] as const) {
    for (let v = 0; v <= 1.0001; v += 0.05) {
      o = rebalance(o, key, Math.round(v * 100) / 100);
      assert.equal(sum(o), 1);
      assert.ok(Object.values(o).every((x) => x >= 0 && x <= 1), JSON.stringify(o));
    }
  }
});
