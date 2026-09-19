"""The design session record: what an iteration keeps and what survives a
save/load round trip. A fake engine stands in for the kernels so these run
in milliseconds and on a machine with no backend installed.
"""

import json
from pathlib import Path

import pytest

from agentcad.config import OutputConfig, ProjectConfig
from agentcad.engine import CADEngine, ExportResult, RenderResult, ValidationResult
from agentcad.session import SESSION_SCHEMA, DesignSession, Iteration


class FakeEngine(CADEngine):
    """Measures a source by reading a number out of it: `volume = 42` in the
    text becomes the reported volume, so tests steer the metadata from the
    source alone."""

    known_settings = ("color",)
    FILE_EXTENSION = ".fake"
    EXPORT_FORMATS = ("stl",)

    @property
    def name(self) -> str:
        return "Fake"

    def available(self) -> bool:
        return True

    def _measure(self, source_path: Path):
        volume = 1.0
        solids = 1
        for line in Path(source_path).read_text().splitlines():
            if line.startswith("volume"):
                volume = float(line.split("=")[1])
            if line.startswith("solids"):
                solids = int(line.split("=")[1])
        return {"volume": volume, "bbox_size": [1.0, 1.0, volume], "counts": {"solids": solids},
                "face_census": {"plane": 6, "cylinder": 0, "cone": 0, "sphere": 0, "torus": 0, "bspline": 0, "other": 0}}

    def render(self, source_path, output_dir, views=None, image_size=1024, defines=None):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        images = {}
        for v in (views or ["iso"]):
            p = output_dir / f"{Path(source_path).stem}_{v}.png"
            p.write_bytes(b"\x89PNG fake")
            images[v] = p
        return RenderResult(images=images, metadata=self._measure(source_path))

    def export(self, source_path, output_path, fmt="stl", defines=None):
        if fmt not in self.EXPORT_FORMATS:
            return self._unsupported_format(fmt)
        Path(output_path).write_bytes(b"solid fake\nendsolid fake\n")
        return ExportResult(output_path=Path(output_path), format=fmt, metadata=self._measure(source_path))

    def validate_syntax(self, code):
        return ValidationResult(valid=True)


@pytest.fixture
def config(tmp_path) -> ProjectConfig:
    return ProjectConfig(output=OutputConfig(base_dir=tmp_path, sub_dir="designs", default_views=["iso"]))


@pytest.fixture
def session(config) -> DesignSession:
    return DesignSession("widget", FakeEngine(), config=config)


def test_an_iteration_keeps_its_metadata_hash_and_report(session):
    a = session.iterate("volume = 10\n")
    b = session.iterate("volume = 12\n")
    assert a.metadata["volume"] == 10.0 and b.metadata["volume"] == 12.0
    assert a.source_hash and a.source_hash != b.source_hash
    assert a.report is not None and a.report.changed is None
    assert b.report.changed is True and b.report.deltas["volume"] == 2.0


def test_no_measurable_change_on_a_changed_source_is_warned(session):
    session.iterate("volume = 10\n")
    again = session.iterate("volume = 10\n# a comment that changes nothing\n")
    assert again.report.changed is False
    assert any("nothing measurable" in w for w in again.report.warnings), again.report.warnings


def test_unexpected_solid_count_is_warned(session):
    it = session.iterate("volume = 10\nsolids = 3\n")
    assert any("solids 3 != expected 1" in w for w in it.report.warnings), it.report.warnings


def test_state_round_trips_with_schema_two(session, config):
    session.iterate("volume = 10\n")
    session.iterate("volume = 12\n")
    session.note("looks right")
    path = session.save_state()
    data = json.loads(path.read_text())
    assert data["schema"] == SESSION_SCHEMA
    assert data["iterations"][1]["metadata"]["volume"] == 12.0
    assert data["iterations"][1]["report"]["deltas"]["volume"] == 2.0

    loaded = DesignSession.load_state("widget", FakeEngine(), config=config)
    assert loaded.iteration_count == 2
    assert loaded.current.metadata["volume"] == 12.0
    assert loaded.current.report.deltas["volume"] == 2.0
    assert loaded.current.source_hash == session.current.source_hash
    assert loaded.current.notes == ["looks right"]


def test_a_schema_one_record_still_loads(session, config):
    session.iterate("volume = 10\n")
    path = session.save_state()
    data = json.loads(path.read_text())
    data.pop("schema")
    for it in data["iterations"]:
        for key in ("metadata", "defines", "source_hash", "report"):
            it.pop(key, None)
    path.write_text(json.dumps(data))

    loaded = DesignSession.load_state("widget", FakeEngine(), config=config)
    it = loaded.current
    assert it.metadata == {} and it.report is None
    assert it.source_hash  # recomputed from the source on disk
    # the next iteration compares against an empty record and does not warn
    nxt = loaded.iterate("volume = 11\n")
    assert nxt.report.changed is None or nxt.report.changed is True
    assert not any("nothing measurable" in w for w in nxt.report.warnings)


def test_iteration_from_dict_tolerates_missing_report():
    it = Iteration.from_dict({"number": 1, "timestamp": "t", "notes": []})
    assert it.report is None and it.metadata == {} and it.defines == {}
