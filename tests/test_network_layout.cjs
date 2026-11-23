"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../src/reconductor/static/network.js"), "utf8");
const begin = source.indexOf("function groupHash(input){");
const end = source.indexOf("class NetworkGraph {", begin);
assert(begin >= 0 && end > begin, "Network layout helpers are defined");
const context = { Math, Map, Set, Object, Number };
vm.runInNewContext(source.slice(begin, end), context);

const family = {id: "g-family", kind: "group", group_kind: "family", label: "Our Family"};
const gcc = {id: "g-gcc", kind: "group", group_kind: "organization", label: "GCC"};
const a = {id: "p-a", kind: "person", label: "Person A"};
const b = {id: "p-b", kind: "person", label: "Person B"};
const c = {id: "p-c", kind: "person", label: "Unconnected Person"};
const view = {
  nodes: [family, gcc, a, b, c],
  edges: [
    {source: "p-a", target: "g-gcc", type: "works at"},
    {source: "p-b", target: "g-gcc", type: "works at"},
  ],
  positions: {},
};
const layout = context.layoutGraph(view);
const distance = (left, right) => Math.hypot(left.x-right.x, left.y-right.y);
assert(distance(layout[a.id], layout[gcc.id]) < distance(layout[c.id], layout[gcc.id]));
assert(distance(layout[b.id], layout[gcc.id]) < distance(layout[c.id], layout[gcc.id]));
assert.equal(layout[gcc.id].y, -305);
assert.equal(view.edges.length, 2, "Layout doesn't invent an A-to-B edge");
const second = context.layoutGraph(view);
assert.deepEqual(JSON.parse(JSON.stringify(layout)), JSON.parse(JSON.stringify(second)), "Layout is stable");
view.positions["p-a"] = {x: 120, y: 15};
assert.equal(context.layoutGraph(view)["p-a"].x, 120, "Dragged position overrides automatic layout");

assert(source.includes("Show other workspaces"), "Memberships are revealed only by explicit action");
assert(source.includes("/memberships"), "Dedicated membership endpoint is called");
console.log("Network auto-clustering and workspace-membership controls: passed");
