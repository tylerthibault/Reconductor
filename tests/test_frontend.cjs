"use strict";

// Exercises the actual browser form listeners without adding a DOM dependency.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const js = fs.readFileSync(path.join(__dirname, "../src/reconductor/static/app.js"), "utf8");
const start = js.indexOf(' $("newForm").addEventListener("input",');
const end = js.indexOf(' $("startButton").addEventListener("click",', start);
assert(start >= 0 && end > start, "Find the new investigation form handlers");
const listeners = new Map();
const nodes = {
  newForm: { addEventListener(type, handler) { listeners.set(type, handler); } },
  planPreview: { hidden: false },
  executionControls: { hidden: false },
  networkAck: { checked: true },
  runConfirm: { value: "RU" },
};

vm.runInNewContext(js.slice(start, end), {
  $: id => {
    assert(id in nodes, "Unexpected element: " + id);
    return nodes[id];
  },
});
const onInput = listeners.get("input");
assert.equal(typeof onInput, "function");

// Changing the acknowledgment checkbox or typing RUN must never collapse the controls.
for (const id of ["networkAck", "runConfirm"]) {
  nodes.planPreview.hidden = false;
  nodes.executionControls.hidden = false;
  nodes.networkAck.checked = true;
  nodes.runConfirm.value = "RU";
  onInput({ target: { closest(selector) {
    assert.equal(selector, "#executionControls");
    return { id };
  } } });
  assert.equal(nodes.planPreview.hidden, false, id + " must keep preview open");
  assert.equal(nodes.executionControls.hidden, false, id + " must keep confirmation open");
  assert.equal(nodes.networkAck.checked, true);
  assert.equal(nodes.runConfirm.value, "RU");
}

// But changing actual investigation parameters must invalidate the plan and consent.
onInput({ target: { closest() { return null; } } });
assert.equal(nodes.planPreview.hidden, true);
assert.equal(nodes.executionControls.hidden, true);
assert.equal(nodes.networkAck.checked, false);
assert.equal(nodes.runConfirm.value, "");

// Pressing Enter in a text input must not submit or navigate away.
let prevented = false;
listeners.get("submit")({ preventDefault() { prevented = true; } });
assert.equal(prevented, true);

console.log("Dashboard confirmation input behavior: passed");
