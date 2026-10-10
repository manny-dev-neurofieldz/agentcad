"""A PrusaSlicer 3MF project: a core 3MF model with the two metadata members PrusaSlicer reads.

Members, in this order:

* ``[Content_Types].xml`` and ``_rels/.rels``: the package skeleton, as PrusaSlicer writes it;
* ``3D/3dmodel.model``: the core 3MF model. One ``<object>`` per part, one ``<item>`` per copy, each
  item's ``transform`` the 12 numbers of the model-to-bed placement in the row-vector convention
  (``p_bed = p_model M``, translation last) exactly as the generic target writes them. The version
  metadata ``slic3rpe:Version3mf`` marks the file as a PrusaSlicer project, so the placement stays
  the instance's transformation instead of being baked into the mesh;
* ``Metadata/Slic3r_PE.config``: the complete configuration, ``; key = value`` lines;
* ``Metadata/Slic3r_PE_model.config``: per object its name, its instance count, its own settings
  (the keys PrusaSlicer lets one object override) and one volume covering all of its triangles.

Everything is written in a fixed order with fixed timestamps, so the same job writes the same bytes.
Support blockers and enforcers (volumes of another type in the same object) are not built: a job
has no vocabulary for the region of one yet.
"""

import zipfile
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from agentcad.gcode.check import THREEMF_CONFIG
from agentcad.targets import Job, TargetError
from agentcad.targets.generic import CORE, to_3mf
from agentcad.targets.prusaslicer_config import format_config

MODEL = "3D/3dmodel.model"
MODEL_CONFIG = "Metadata/Slic3r_PE_model.config"
SLIC3RPE = "http://schemas.slic3r.org/3mf/2017/06"
VERSION_3MF = 1                              # the project version PrusaSlicer writes and reads
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)          # every member stamped alike
_IDENTITY_16 = "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"

_CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                  '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
                  ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
                  ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
                  '</Types>\n')
_RELATIONSHIPS = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                  '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
                  ' <Relationship Target="/3D/3dmodel.model" Id="rel-1" '
                  'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
                  '</Relationships>\n')


def _q(value: Any) -> str:
    """An attribute value, quoted and escaped."""
    return quoteattr(str(value))


def model_xml(job: Job, instances: Sequence[Dict[str, Any]], meshes: Dict[str, Tuple[Any, Any]],
              ids: Dict[str, int]) -> str:
    """The core model: every part's mesh as an object, every copy as a build item."""
    out: List[str] = ['<?xml version="1.0" encoding="UTF-8"?>',
                      f'<model unit="millimeter" xml:lang="en-US" xmlns="{CORE}" xmlns:slic3rpe="{SLIC3RPE}">',
                      f' <metadata name="slic3rpe:Version3mf">{VERSION_3MF}</metadata>',
                      f' <metadata name="Title">{escape(job.name)}</metadata>',
                      ' <metadata name="Application">agentcad</metadata>',
                      ' <resources>']
    for part in job.parts:
        points, triangles = meshes[part.name]
        out.append(f'  <object id="{ids[part.name]}" type="model" name={_q(part.name)}>')
        out.append('   <mesh>')
        out.append('    <vertices>')
        out += [f'     <vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>' for x, y, z in points.tolist()]
        out.append('    </vertices>')
        out.append('    <triangles>')
        out += [f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in triangles.tolist()]
        out.append('    </triangles>')
        out.append('   </mesh>')
        out.append('  </object>')
    out.append(' </resources>')
    out.append(' <build>')
    for inst in instances:
        out.append(f'  <item objectid="{ids[inst["part"]]}" transform="{to_3mf(inst["transform"])}" printable="1"/>')
    out.append(' </build>')
    out.append('</model>')
    return "\n".join(out) + "\n"


def model_config_xml(job: Job, instances: Sequence[Dict[str, Any]], meshes: Dict[str, Tuple[Any, Any]],
                     ids: Dict[str, int], object_settings: Sequence[Dict[str, str]]) -> str:
    """What PrusaSlicer reads about each object: its name, its settings, and one volume over all its triangles."""
    copies: Dict[str, int] = {}
    for inst in instances:
        copies[inst["part"]] = copies.get(inst["part"], 0) + 1
    out: List[str] = ['<?xml version="1.0" encoding="UTF-8"?>', '<config>']
    for part, settings in zip(job.parts, object_settings):
        out.append(f' <object id="{ids[part.name]}" instances_count="{copies.get(part.name, 0)}">')
        out.append(f'  <metadata type="object" key="name" value={_q(part.name)}/>')
        for key in sorted(settings):
            out.append(f'  <metadata type="object" key={_q(key)} value={_q(settings[key])}/>')
        out.append(f'  <volume firstid="0" lastid="{len(meshes[part.name][1]) - 1}">')
        out.append(f'   <metadata type="volume" key="name" value={_q(part.name)}/>')
        out.append('   <metadata type="volume" key="volume_type" value="ModelPart"/>')
        out.append(f'   <metadata type="volume" key="matrix" value="{_IDENTITY_16}"/>')
        out.append('  </volume>')
        out.append(' </object>')
    out.append('</config>')
    return "\n".join(out) + "\n"


def write_project(path: Path, job: Job, instances: Sequence[Dict[str, Any]], meshes: Dict[str, Tuple[Any, Any]],
                  settings: Dict[str, str], object_settings: Sequence[Dict[str, str]]) -> Path:
    """Write the project. Every text is built before the file is opened, so a refusal leaves no file behind."""
    ids = {part.name: i for i, part in enumerate(job.parts, start=1)}
    members = [
        ("[Content_Types].xml", _CONTENT_TYPES),
        ("_rels/.rels", _RELATIONSHIPS),
        (MODEL, model_xml(job, instances, meshes, ids)),
        (THREEMF_CONFIG, format_config(settings, "generated by agentcad (the prusaslicer target)")),
        (MODEL_CONFIG, model_config_xml(job, instances, meshes, ids, object_settings)),
    ]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, text in members:
            info = zipfile.ZipInfo(name, date_time=_FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3                   # the same on every platform
            info.external_attr = 0o644 << 16
            z.writestr(info, text)
    return path


def read_model_config(path: Path) -> Dict[str, Dict[str, Any]]:
    """The objects of a project's ``Slic3r_PE_model.config`` by object id: ``name``, ``instances`` (the count
    it states), ``settings`` (the object's own keys) and ``volumes`` (first and last triangle, name, type).
    TargetError for a file that is not a PrusaSlicer project."""
    try:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read(MODEL_CONFIG))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
        raise TargetError(f"{Path(path).name} has no readable {MODEL_CONFIG}: {e}") from None
    objects: Dict[str, Dict[str, Any]] = {}
    for obj in root.iter("object"):
        meta = {m.get("key"): m.get("value") for m in obj.findall("metadata") if m.get("type") == "object"}
        volumes = []
        for vol in obj.findall("volume"):
            vmeta = {m.get("key"): m.get("value") for m in vol.findall("metadata")}
            volumes.append({"first": int(vol.get("firstid")), "last": int(vol.get("lastid")),
                            "name": vmeta.get("name"), "type": vmeta.get("volume_type")})
        objects[obj.get("id")] = {"name": meta.pop("name", None), "instances": int(obj.get("instances_count", 0)),
                                  "settings": meta, "volumes": volumes}
    return objects
