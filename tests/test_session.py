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


# --- session integrity (reopen, archive, per-iteration defines, tags, parts) ---

def test_finalize_is_idempotent_and_reopen_continues_numbering(session):
    session.iterate("volume = 10\n")
    first = session.finalize()
    assert first.exists()
    exports_before = sorted(p.name for p in session.project.exports_dir.iterdir())
    second = session.finalize()          # no raise, same page, nothing duplicated
    assert second == first
    assert sorted(p.name for p in session.project.exports_dir.iterdir()) == exports_before
    assert len(session.project.variants) == 1

    session.reopen()
    it = session.iterate("volume = 11\n")
    assert it.number == 2
    session.finalize()
    assert (session.project.exports_dir / "widget_v2.stl").exists()
    assert len(session.project.variants) == 2


def test_archive_previous_moves_the_record_instead_of_clobbering_it(session, config):
    session.iterate("volume = 10\n")
    session.finalize()
    session.save_state()
    old_record = session.state_file.read_bytes()
    old_render = session.current.image_paths["iso"]
    assert old_render.exists()

    archive = DesignSession.archive_previous("widget", config=config, reason="restart for a new draft")
    assert archive is not None and archive.is_dir()
    assert (archive / "session.json").read_bytes() == old_record
    assert not session.state_file.exists()
    assert not old_render.exists() and (archive / "v1" / old_render.name).exists()
    assert "restart for a new draft" in (archive / "NOTE.txt").read_text()

    fresh = DesignSession("widget", FakeEngine(), config=config)
    it = fresh.iterate("volume = 5\n")
    assert it.number == 1
    fresh.save_state()
    second = DesignSession.archive_previous("widget", config=config, reason="again")
    assert second is not None and second != archive
    assert DesignSession.archive_previous("widget", config=config, reason="nothing there") is None


def test_per_iteration_defines_layer_on_the_session_defines(config):
    session = DesignSession("widget", FakeEngine(), config=config, defines={"a": "1"})
    plain = session.iterate("volume = 10\n")
    tuned = session.iterate("volume = 10\n", defines={"b": "2"})
    assert plain.defines == {"a": "1"}
    assert tuned.defines == {"a": "1", "b": "2"}
    assert session.defines == {"a": "1"}          # the session's own defines are untouched
    session.save_state()
    loaded = DesignSession.load_state("widget", FakeEngine(), config=config)
    assert loaded.iterations[1].defines == {"a": "1", "b": "2"}


def test_tag_freezes_the_latest_iteration_and_refuses_to_overwrite(session):
    session.iterate("volume = 10\n")
    session.iterate("volume = 12\n")
    tag_dir = session.tag("draft1", note="sent to the reviewer")
    assert tag_dir == session.project.project_dir / "tags" / "draft1"
    assert (tag_dir / "source" / "widget_v2.fake").read_text() == "volume = 12\n"
    assert (tag_dir / "renders" / "widget_v2_iso.png").exists()
    assert (tag_dir / "exports" / "widget_v2.stl").exists()
    meta = json.loads((tag_dir / "TAG.json").read_text())
    assert meta["iteration"] == 2 and meta["note"] == "sent to the reviewer"
    assert meta["metadata"]["volume"] == 12.0
    with pytest.raises(FileExistsError):
        session.tag("draft1")
    session.save_state()
    loaded = DesignSession.load_state("widget", FakeEngine(), config=session.config)
    assert "draft1" in loaded.tags and loaded.tags["draft1"]["iteration"] == 2


def _part_project(root: Path, parent: str, part: str, extra: str = "") -> Path:
    d = root / "designs" / parent / "parts" / part
    d.mkdir(parents=True)
    (d / "agentcad.toml").write_text(
        f'[project]\nname = "{part}"\nengine = "openscad"\n'
        f'[output]\nbase_dir = "{root / "designs" / parent}"\nsub_dir = "parts"\n{extra}'
    )
    return d


def test_a_parent_project_declares_its_parts_and_iterates_them_all(tmp_path):
    from agentcad.config import ProjectConfig, list_projects

    parent = tmp_path / "designs" / "asm"
    parent.mkdir(parents=True)
    (parent / "agentcad.toml").write_text(
        f'[project]\nname = "asm"\nengine = "openscad"\nparts = ["parts/*"]\n'
        f'[output]\nbase_dir = "{tmp_path}"\nsub_dir = "designs"\n'
    )
    _part_project(tmp_path, "asm", "lid")
    _part_project(tmp_path, "asm", "base")

    cfg = ProjectConfig.load(parent / "agentcad.toml")
    parts = cfg.part_projects()
    assert [p.name for _, p in parts] == ["base", "lid"]
    listed = list_projects(tmp_path / "designs")
    assert [(c.name, c.parent_name) for c in listed] == [("asm", None), ("base", "asm"), ("lid", "asm")]

    solo = ProjectConfig.load(_part_project(tmp_path, "solo", "x") / "agentcad.toml")
    assert solo.part_projects() == []


def test_finalize_re_exports_when_the_source_is_newer_than_its_export(session):
    import os, time
    session.iterate("volume = 10\n")
    session.finalize()
    export = session.project.exports_dir / "widget_v1.stl"
    first = export.stat().st_mtime
    # an export older than its source is not the same geometry: re-export
    old = first - 100
    os.utime(export, (old, old))
    session.finalize()
    assert export.stat().st_mtime > old
    # an export newer than its source is reused: no rewrite
    time.sleep(0.01)
    kept = export.stat().st_mtime
    session.finalize()
    assert export.stat().st_mtime == kept


def test_files_of_an_unrecorded_session_move_aside_instead_of_being_overwritten(session, capsys):
    stray = session._work_dir / "widget_v1.fake"
    stray.write_text("volume = 99\n")
    (session._work_dir / "v1").mkdir()
    (session._work_dir / "v1" / "widget_v1_iso.png").write_bytes(b"old")
    it = session.iterate("volume = 10\n")
    assert it.number == 1 and it.source_path.read_text() == "volume = 10\n"
    aside = [p for p in session._work_dir.iterdir() if p.name.startswith("stale_")]
    assert len(aside) == 1
    assert (aside[0] / "widget_v1.fake").read_text() == "volume = 99\n"
    assert (aside[0] / "v1" / "widget_v1_iso.png").read_bytes() == b"old"
    assert "moved to" in capsys.readouterr().err


def test_manifest_lists_parts_with_quantities_and_keeps_fit_results(session):
    from agentcad.manifest import PrintManifest
    session.iterate("volume = 10\n")
    session.part_meshes = [("lid", session.project.exports_dir / "lid_v1.stl", 1), ("peg", session.project.exports_dir / "peg_v1.stl", 3)]
    session.finalize()
    path = session.project.exports_dir / "widget.print.json"
    m = PrintManifest.load(path)
    assert [(p["name"], p["quantity"]) for p in m.parts] == [("lid", 1), ("peg", 3)] and m.part_count() == 4
    m.fit = [{"a": "lid", "b": "peg", "interference_mm3": 0.0, "clearance_mm": 0.15, "windows": {}}]
    m.save(path)
    session.finalize()                                   # a re-finalize keeps the recorded fit
    assert PrintManifest.load(path).fit[0]["clearance_mm"] == 0.15
    single = PrintManifest(part_name="solo", project_name="solo", stl_filename="solo_v1.stl")
    assert single.part_count() == 1
