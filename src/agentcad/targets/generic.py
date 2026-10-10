"""The generic output target: a core 3MF plate any slicer opens, with a placement sidecar, and
the settings of a sliced file (plain or binary G-code) read through the existing reader. It writes
no slicer settings; a slicer's own target does that.

Placement, schema ``agentcad.placement/2``: per instance, the part, its copy number, its mesh
file and that file's SHA-256, the target, and ``transform``, a row-major 4x4 acting on column
vectors (``p_bed = T p_model``), translation in the last column. A 3MF build item stores the same
placement as 12 numbers in the row-vector convention (``p_bed = p_model M``): the rows of the
3 x 3 part of ``T``'s transpose, then the translation, last. Converting one to the other is a
transpose, which is exactly the mistake an asymmetric placement exposes.
"""

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Sequence
from xml.etree import ElementTree as ET

from agentcad.targets import Job, OutputTarget

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
CONVENTION = ("transform: row-major 4x4 acting on column vectors (p_bed = T p_model), translation in the last "
              "column; a 3MF build item stores it as 12 numbers in the row vector convention (p_bed = p_model M, "
              "M the transpose), translation last")
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)            # every member stamped alike: the same job writes the same bytes
_GAP_MM = 5.0                                  # between copies laid out along x


def to_3mf(T: Sequence[Sequence[float]]) -> str:
    """A model-to-bed transform as a 3MF build item's 12 numbers."""
    numbers = [T[r][c] for c in range(3) for r in range(3)] + [T[r][3] for r in range(3)]
    return " ".join(f"{float(v):.9g}" for v in numbers)


def from_3mf(text: str) -> List[List[float]]:
    """A 3MF build item's 12 numbers as a row-major 4x4 acting on column vectors."""
    n = [float(v) for v in text.split()]
    if len(n) != 12:
        raise ValueError(f"a 3MF transform has 12 numbers, not {len(n)}: {text!r}")
    T = [[n[3 * c + r] for c in range(3)] + [n[9 + r]] for r in range(3)]
    return T + [[0.0, 0.0, 0.0, 1.0]]


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _mesh(stl: Path):
    import numpy as np
    from agentcad.meshmeasure import read_stl
    V, _ = read_stl(Path(stl))
    points, index = np.unique(np.round(V, 6), axis=0, return_inverse=True)
    return points, index.reshape(-1, 3)


def instances(job: Job) -> List[Dict[str, Any]]:
    """Every copy of every part with its transform: copies after the first sit along +x, each a
    part's width plus a gap from the last."""
    out = []
    for part in job.parts:
        width = 0.0
        if part.copies > 1:
            points, _ = _mesh(part.stl)
            width = float(points[:, 0].max() - points[:, 0].min())
        for k in range(max(1, int(part.copies))):
            T = [list(map(float, row)) for row in part.transform]
            T[0][3] += k * (width + _GAP_MM)
            out.append({"part": part.name, "copy": k + 1, "stl": Path(part.stl).name, "transform": T,
                        "sha256": _sha256(part.stl)})
    return out


def placement(job: Job, target: str) -> Dict[str, Any]:
    return {"schema": "agentcad.placement/2", "job": job.name, "convention": CONVENTION,
            "instances": [dict(inst, target=target) for inst in instances(job)]}


def write_plate(job: Job, path: Path) -> Path:
    """A core 3MF: one object per part, one build item per copy."""
    ET.register_namespace("", CORE)
    model = ET.Element(f"{{{CORE}}}model", {"unit": "millimeter"})
    resources = ET.SubElement(model, f"{{{CORE}}}resources")
    build = ET.SubElement(model, f"{{{CORE}}}build")
    object_id = {}
    for i, part in enumerate(job.parts, start=1):
        points, tris = _mesh(part.stl)
        obj = ET.SubElement(resources, f"{{{CORE}}}object", {"id": str(i), "type": "model", "name": part.name})
        mesh = ET.SubElement(obj, f"{{{CORE}}}mesh")
        verts = ET.SubElement(mesh, f"{{{CORE}}}vertices")
        for x, y, z in points:
            ET.SubElement(verts, f"{{{CORE}}}vertex", {"x": f"{x:.6f}", "y": f"{y:.6f}", "z": f"{z:.6f}"})
        triangles = ET.SubElement(mesh, f"{{{CORE}}}triangles")
        for a, b, c in tris:
            ET.SubElement(triangles, f"{{{CORE}}}triangle", {"v1": str(a), "v2": str(b), "v3": str(c)})
        object_id[part.name] = str(i)
    for inst in instances(job):
        ET.SubElement(build, f"{{{CORE}}}item", {"objectid": object_id[inst["part"]], "transform": to_3mf(inst["transform"])})
    members = {
        "[Content_Types].xml": ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/'
                                'package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.'
                                'openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType='
                                '"application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>\n'),
        "_rels/.rels": ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/'
                        'package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type='
                        '"http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>\n'),
        "3D/3dmodel.model": '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(model, encoding="unicode") + "\n",
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in members.items():
            z.writestr(zipfile.ZipInfo(name, date_time=_FIXED_TIME), text)
    return path


def read_plate(path: Path) -> List[Dict[str, Any]]:
    """The build items of a 3MF: object id, the object's name and the transform as a 4x4."""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("3D/3dmodel.model"))
    names = {o.get("id"): o.get("name") for o in root.iter(f"{{{CORE}}}object")}
    identity = "1 0 0 0 1 0 0 0 1 0 0 0"
    return [{"objectid": item.get("objectid"), "name": names.get(item.get("objectid")),
             "transform": from_3mf(item.get("transform") or identity)}
            for item in root.iter(f"{{{CORE}}}item")]


class GenericTarget(OutputTarget):
    name = "generic"
    capabilities = frozenset({"write_job", "read_output"})

    def write_job(self, job: Job, out_dir: Path) -> List[Path]:
        out_dir = Path(out_dir)
        plate = write_plate(job, out_dir / f"{job.name}.3mf")
        sidecar = out_dir / f"{job.name}.placement.json"
        sidecar.write_text(json.dumps(placement(job, self.name), indent=1) + "\n")
        return [plate, sidecar]

    def read_settings(self, path: Path) -> Dict[str, str]:
        from agentcad.gcode.check import embedded_config
        return embedded_config(Path(path))
