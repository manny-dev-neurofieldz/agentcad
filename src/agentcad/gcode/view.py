"""A standalone page showing a sliced file's toolpaths: per-feature colours with toggles, a layer slider.

Offline by default: the vendored three.js and OrbitControls are inlined, and the toolpaths are embedded
packed (``toolpaths.pack``) within the budget; when layers were dropped to fit, the page says so.
"""

import json
from pathlib import Path

from agentcad.gcode.model import GCodeModel
from agentcad.gcode.toolpaths import pack

VENDOR = Path(__file__).resolve().parent.parent / "templates" / "vendor"

COLOURS = {
    "Perimeter": "#f2a03d", "External perimeter": "#e8661c", "Overhang perimeter": "#2a6fdb",
    "Internal infill": "#b23a48", "Solid infill": "#8e44ad", "Top solid infill": "#e74c3c",
    "Bridge infill": "#5dade2", "Gap fill": "#ffffff", "Skirt/Brim": "#27ae60",
    "Support material": "#2ecc71", "Support material interface": "#16a085", "Custom": "#7f8c8d",
}

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{margin:0;background:#1d1f21;color:#ddd;font:13px sans-serif}}#ui{{position:absolute;top:8px;left:8px;
background:#000a;padding:8px;border-radius:6px}}label{{display:block}}#note{{color:#f39c12}}</style></head><body>
<div id="ui"><b>{title}</b><div id="note">{note}</div><div id="legend"></div>
layers <input id="lo" type="range" min="0" max="{nmax}" value="0"> to
<input id="hi" type="range" min="0" max="{nmax}" value="{nmax}"> <span id="zr"></span></div>
<script>{three}</script><script>{orbit}</script>
<script>
const DATA = {data}; const COLOURS = {colours};
const scene = new THREE.Scene(); const cam = new THREE.PerspectiveCamera(45, innerWidth / innerHeight, 0.1, 5000);
const r = new THREE.WebGLRenderer({{antialias: true}}); r.setSize(innerWidth, innerHeight); document.body.appendChild(r.domElement);
cam.up.set(0, 0, 1); const ctl = new THREE.OrbitControls(cam, r.domElement);
const groups = {{}}; const layerObjs = [];
function dec(b64) {{ const s = atob(b64); const u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i); return new Float32Array(u.buffer); }}
DATA.layers.forEach((L, i) => {{ for (const [f, b] of Object.entries(L.features)) {{
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(dec(b), 3));
  const m = new THREE.LineSegments(g, new THREE.LineBasicMaterial({{color: COLOURS[f] || "#cccccc"}}));
  m.userData = {{feature: f, layer: i}}; scene.add(m); layerObjs.push(m); groups[f] = true; }} }});
const box = new THREE.Box3().setFromObject(scene); const c = box.getCenter(new THREE.Vector3()); const sz = box.getSize(new THREE.Vector3()).length();
ctl.target.copy(c); cam.position.set(c.x + sz, c.y - sz, c.z + sz * 0.8); ctl.update();
const leg = document.getElementById("legend");
Object.keys(groups).forEach(f => {{ const l = document.createElement("label");
  l.innerHTML = `<input type=checkbox checked data-f="${{f}}"> <span style="color:${{COLOURS[f] || '#ccc'}}">&#9632;</span> ${{f}}`; leg.appendChild(l); }});
function apply() {{ const lo = +document.getElementById("lo").value, hi = +document.getElementById("hi").value;
  const on = {{}}; document.querySelectorAll("#legend input").forEach(i => on[i.dataset.f] = i.checked);
  layerObjs.forEach(m => m.visible = on[m.userData.feature] && m.userData.layer >= lo && m.userData.layer <= hi);
  document.getElementById("zr").textContent = `z ${{DATA.layers[lo].z}}-${{DATA.layers[hi].z}} mm`; }}
document.querySelectorAll("input").forEach(i => i.addEventListener("input", apply)); apply();
(function loop() {{ requestAnimationFrame(loop); r.render(scene, cam); }})();
</script></body></html>"""


def write_page(model: GCodeModel, out: Path, title: str = "toolpaths", budget_mb: float = 8.0) -> Path:
    data = pack(model, int(budget_mb * 1024 * 1024))
    note = (f"every {data['stride']}th layer shown (the full print exceeds the {budget_mb:g} MB embed budget)"
            if data["stride"] > 1 else "")
    html = PAGE.format(title=title, note=note, nmax=max(0, len(data["layers"]) - 1),
                       three=(VENDOR / "three.min.js").read_text(), orbit=(VENDOR / "OrbitControls.js").read_text(),
                       data=json.dumps(data), colours=json.dumps(COLOURS))
    out = Path(out)
    out.write_text(html, encoding="utf-8")
    return out
