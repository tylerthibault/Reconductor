"use strict";
// Regression: check output and card badge must show the same test result.
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"../src/reconductor/static/tools.js"),"utf8");
const start=source.indexOf("function startupStatusLabel(status){");
const end=source.indexOf("function card(tool){",start);
assert(start>=0&&end>start,"Tool status UI functions are available");
const context={String};vm.runInNewContext(source.slice(start,end),context);
const badge={className:"tool-status detected",textContent:"Detected · untested"};
context.applyBadge(badge,"ready");
assert.equal(badge.className,"tool-status ready");
assert.equal(badge.textContent,"READY · STARTUP CHECK PASSED");
context.applyBadge(badge,"broken");
assert.equal(badge.className,"tool-status broken");
assert.equal(badge.textContent,"STARTUP FAILED");
assert.match(source,/applyBadge\(badge,report.status\)/,
 "Startup result must immediately update the on-screen badge");
assert.match(source,/tool\.status=report\.status/,
 "Tool data must update when a test finishes");
console.log("Tool Manager startup badge synchronization: passed");
