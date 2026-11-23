"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const source=fs.readFileSync(path.join(__dirname,"../src/reconductor/static/app.js"),"utf8");
const start=source.indexOf("function groupFindings(findings){");
const end=source.indexOf("function showResearchGroup(parent,group){",start);
assert(start>=0&&end>start,"Readable results functions present");
const context={URL};
vm.runInNewContext(source.slice(start,end),context);
const groups=context.groupFindings([
 {category:"username",display_name:"janedoe"},
 {category:"profile",display_name:"Codewars",url:"https://www.codewars.com/users/janedoe"},
 {category:"other",display_name:"example.org"}
]);
assert.equal(groups.length,3);
assert.equal(groups[0].title,"Possible website profiles");
assert.equal(groups[0].items.length,1);
assert.equal(groups[1].title,"Usernames worth checking");
assert.equal(groups[1].items.length,1);
assert.equal(context.externalLabel("https://www.codewars.com/users/janedoe"),"codewars.com/users/janedoe");
assert.match(source,/f\.display_name\|\|f\.value/);
assert.match(source,/Reported by .*Not verified/);
assert.match(source,/getElementById/);
console.log("Readable research grouping: passed");
