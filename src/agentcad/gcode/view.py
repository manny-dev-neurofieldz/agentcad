"""A standalone page showing a sliced file's toolpaths: per-feature colours with toggles, a layer slider.

Offline by default: the vendored three.js and OrbitControls are inlined, and the toolpaths are embedded
packed (``toolpaths.pack``) within the budget; when layers were dropped to fit, the page says so.
"""

import json
from importlib import resources
from pathlib import Path

from agentcad.gcode.model import GCodeModel
from agentcad.gcode.toolpaths import pack

# Package data located by the package's name, not by climbing from this file.
VENDOR = resources.files("agentcad.templates") / "vendor"

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
// overlays: the placed parts, and support contacts per kind (sorted by z, so the layer range is a draw range)
const extras = [];
const parts = (DATA.meshes || []).map(M => {{ const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(dec(M.p), 3));
  const s = atob(M.t); const u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i);
  g.setIndex(new THREE.BufferAttribute(new Uint32Array(u.buffer), 1)); g.computeVertexNormals();
  const m = new THREE.Mesh(g, new THREE.MeshBasicMaterial({{color: "#9fb4d0", transparent: true, opacity: 0.18}}));
  scene.add(m); return m; }});
if (parts.length) extras.push({{name: "Parts", colour: "#9fb4d0", objs: parts}});
[["outside", "Support contacts (outside)", "#20ff60"], ["cavity", "Support contacts (in a cavity)", "#ff2020"]]
  .forEach(([kind, name, col]) => {{
  const cs = (DATA.contacts || []).filter(c => c[3] === kind).sort((p, q) => p[2] - q[2]); if (!cs.length) return;
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(cs.flatMap(c => [c[0], c[1], c[2]])), 3));
  const m = new THREE.Points(g, new THREE.PointsMaterial({{color: col, size: 0.5}})); m.userData.zs = cs.map(c => c[2]);
  scene.add(m); extras.push({{name: name, colour: col, objs: [m]}}); }});
const leg = document.getElementById("legend");
const entries = Object.keys(groups).map(f => [f, COLOURS[f] || "#ccc"]).concat(extras.map(e => [e.name, e.colour]));
entries.forEach(([f, col]) => {{ const l = document.createElement("label");
  l.innerHTML = `<input type=checkbox checked data-f="${{f}}"> <span style="color:${{col}}">&#9632;</span> ${{f}}`; leg.appendChild(l); }});
function apply() {{ const lo = +document.getElementById("lo").value, hi = +document.getElementById("hi").value;
  const on = {{}}; document.querySelectorAll("#legend input").forEach(i => on[i.dataset.f] = i.checked);
  layerObjs.forEach(m => m.visible = !!on[m.userData.feature] && m.userData.layer >= lo && m.userData.layer <= hi);
  const zlo = DATA.layers[lo].z - 1e-6, zhi = DATA.layers[hi].z + 1e-6;
  extras.forEach(e => e.objs.forEach(m => {{ m.visible = !!on[e.name];
    if (m.userData.zs) {{ const zs = m.userData.zs; let a = 0, b = zs.length;
      while (a < zs.length && zs[a] < zlo) a++; while (b > a && zs[b - 1] > zhi) b--; m.geometry.setDrawRange(a, b - a); }} }}));
  document.getElementById("zr").textContent = `z ${{DATA.layers[lo].z}}-${{DATA.layers[hi].z}} mm`; }}
document.querySelectorAll("input").forEach(i => i.addEventListener("input", apply)); apply();
(function loop() {{ requestAnimationFrame(loop); r.render(scene, cam); }})();
</script></body></html>"""


def ordinal(n: int) -> str:
    """2 -> "2nd", 11 -> "11th", 21 -> "21st"."""
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def write_page(model: GCodeModel, out: Path, title: str = "toolpaths", budget_mb: float = 8.0,
               contacts=None, meshes=None, fragment: bool = False) -> Path:
    """``fragment``: write the page without its document shell (doctype, html, head, body), for an artifact host
    that supplies one, plus an empty ``files.json`` beside it (everything is inline).
    ``contacts``: optional [(x, y, z, "outside" | "cavity")] support contact cells (bed frame), drawn as dots.
    ``meshes``: optional [(points (N, 3) in the bed frame, triangles (M, 3))], drawn translucent under the paths."""
    import base64

    import numpy as np

    data = pack(model, int(budget_mb * 1024 * 1024))
    data["meshes"] = [{"p": base64.b64encode(np.asarray(pts, np.float32).tobytes()).decode("ascii"),
                       "t": base64.b64encode(np.asarray(tri, np.uint32).tobytes()).decode("ascii")}
                      for pts, tri in (meshes or [])]
    data["contacts"] = [[float(x), float(y), float(z), kind] for x, y, z, kind in (contacts or [])]
    note = (f"every {ordinal(data['stride'])} layer shown (the full print exceeds the {budget_mb:g} MB embed budget)"
            if data["stride"] > 1 else "")
    html = PAGE.format(title=title, note=note, nmax=max(0, len(data["layers"]) - 1),
                       three=(VENDOR / "three.min.js").read_text(), orbit=(VENDOR / "OrbitControls.js").read_text(),
                       data=json.dumps(data), colours=json.dumps(COLOURS))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if fragment:
        for tag in ("<!doctype html>", "<html>", "<head>", '<meta charset="utf-8">',
                    "</head>", "<body>", "</body>", "</html>"):
            html = html.replace(tag, "", 1)
        (out.parent / "files.json").write_text("{}\n")
    out.write_text(html, encoding="utf-8")
    return out
