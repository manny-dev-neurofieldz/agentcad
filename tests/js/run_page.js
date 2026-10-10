const fs = require("fs"), vm = require("vm");
// Runs a toolpath page's scripts (three.js, OrbitControls, the page) with a stub DOM and a stub renderer,
// and prints what the page built as JSON. A page that throws exits non-zero.
// argv: <dir with page_script_N.js> <index of the "hi" layer> [off: every legend checkbox unchecked]
const dir = process.argv[2], allOff = process.argv[4] === "off";
const el = () => ({style: {}, children: [], appendChild(c) { this.children.push(c); }, addEventListener() {},
  removeEventListener() {}, setPointerCapture() {}, getRootNode() { return doc; }, ownerDocument: null,
  getBoundingClientRect: () => ({left: 0, top: 0, width: 1200, height: 800}), clientWidth: 1200, clientHeight: 800});
const ids = {}; const inputs = [];
const doc = { body: el(), createElement: () => { const e = el(); return e; },
  getElementById: id => ids[id] || (ids[id] = Object.assign(el(), {value: id === "lo" ? "0" : String(+process.argv[3] || 0), textContent: ""})),
  querySelectorAll: () => legendInputs(), addEventListener() {}, removeEventListener() {} };
const inputCache = {};
function legendInputs() {   // one stub input per legend label, keyed by its data-f
  return (ids.legend ? ids.legend.children : []).map(l => {
    const f = /data-f="([^"]*)"/.exec(l.innerHTML || "")[1];
    return inputCache[f] || (inputCache[f] = {dataset: {f}, checked: !allOff, addEventListener() {}});
  });
}
let frames = 0;
const ctx = { document: doc, window: {}, self: {}, innerWidth: 1200, innerHeight: 800, console,
  atob: s => Buffer.from(s, "base64").toString("binary"),
  requestAnimationFrame: f => { if (frames++ < 2) setImmediate(f); }, setTimeout, performance };
ctx.window = ctx; ctx.self = ctx; ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(dir + "/page_script_0.js", "utf8"), ctx);
let renders = 0, objs = 0, shown = 0;
const drawn = o => o.visible && (!o.geometry || o.geometry.drawRange.count > 0);
ctx.THREE.WebGLRenderer = function () { return { domElement: el(), setSize() {}, render(scene) {
  renders++; objs = scene.children.length; shown = scene.children.filter(drawn).length; } }; };
vm.runInContext(fs.readFileSync(dir + "/page_script_1.js", "utf8"), ctx);
vm.runInContext(fs.readFileSync(dir + "/page_script_2.js", "utf8"), ctx);
setTimeout(() => console.log(JSON.stringify({renders, objects: objs, shown, zr: ids.zr && ids.zr.textContent,
  legend: ids.legend.children.length})), 200);
