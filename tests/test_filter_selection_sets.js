/**
 * Simulates filter reload cycles: selections must survive populate/render.
 * Run: node tests/test_filter_selection_sets.js
 */

const assert = require("assert");

const seriesSelectedValues = new Set();
const stateSelectedValues = new Set();
const facetSelectedValues = new Map();

function getFacetSelectionSet(id) {
  if (!facetSelectedValues.has(id)) facetSelectedValues.set(id, new Set());
  return facetSelectedValues.get(id);
}

function selectedMultiValues(id) {
  if (id === "series-values") return [...seriesSelectedValues];
  if (id === "state-codes") return [...stateSelectedValues];
  return [...getFacetSelectionSet(id)];
}

function simulateReload(filterId, apiItems, selectedBefore) {
  const preserved = new Set(selectedBefore);
  // Repopulate from API (like loadFilters -> populateFacetButtonList)
  const visibleValues = new Set(apiItems.map((item) => item.value));
  // Selection Set is independent of DOM — never delete on reload
  for (const value of preserved) {
    getFacetSelectionSet(filterId).add(value);
  }
  return selectedMultiValues(filterId);
}

const allModels = [
  { value: "Corolla LE", available: true },
  { value: "Corolla SE", available: true },
  { value: "Camry LE", available: true },
];

// User selects Corolla LE
getFacetSelectionSet("model-values").add("Corolla LE");
assert.deepStrictEqual(selectedMultiValues("model-values"), ["Corolla LE"]);

// After filter reload, API still returns all models (availability may change)
const afterReload = simulateReload("model-values", allModels, ["Corolla LE"]);
assert.deepStrictEqual(afterReload, ["Corolla LE"], "model selection lost after reload");

// Add second model
getFacetSelectionSet("model-values").add("Camry LE");
assert.strictEqual(selectedMultiValues("model-values").length, 2);

// Reload again
const afterSecondReload = simulateReload("model-values", allModels, selectedMultiValues("model-values"));
assert.strictEqual(afterSecondReload.length, 2, "multi-select lost after second reload");

// Series + state independent sets
seriesSelectedValues.add("corolla");
stateSelectedValues.add("CA");
getFacetSelectionSet("drivetrain-codes").add("FWD");
simulateReload("drivetrain-codes", [{ value: "FWD" }, { value: "AWD" }], ["FWD"]);
assert.deepStrictEqual(selectedMultiValues("series-values"), ["corolla"]);
assert.deepStrictEqual(selectedMultiValues("state-codes"), ["CA"]);
assert.deepStrictEqual(selectedMultiValues("drivetrain-codes"), ["FWD"]);

console.log("OK: filter selection set simulation passed");
