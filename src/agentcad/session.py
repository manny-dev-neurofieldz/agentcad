"""Design session - iteration lifecycle for the agentic feedback loop.

A DesignSession tracks the full history of a design's evolution:
each iteration captures the source code, rendered views, analysis notes,
and any modifications. The session integrates with DesignProject for
organized output and HTML viewer generation.

The agent drives the loop:
    1. session.iterate(code) - saves code, renders views
    2. Agent reads PNGs via Read tool, analyzes visually
    3. session.note(text) - records analysis/observations
    4. Agent modifies code, calls session.iterate(new_code)
    5. session.finalize() - exports STL, generates HTML viewer

Usage:
    session = DesignSession("bracket", engine)
    it = session.iterate(scad_code)          # renders, returns iteration
    session.note("Holes look solid, need tag('remove')")
    it = session.iterate(fixed_code)         # re-renders
    session.note("Through-holes confirmed from bottom view")
    result = session.finalize()              # STL + HTML viewer
"""

import hashlib
import json
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentcad.config import OutputConfig, ProjectConfig
from agentcad.engine import CADEngine, RenderResult
from agentcad.output import DesignProject
from agentcad.report import Report, feature_effect

SESSION_STATE_FILE = "session.json"
#: Session record schema. 1: iterations carried paths and notes only.
#: 2: each iteration also keeps the measured metadata it was rendered with,
#: the defines in force, a hash of its source, and the feature-effect report
#: against the previous iteration. A v1 file loads with those fields absent.
SESSION_SCHEMA = 2


@dataclass
class Iteration:
    """One iteration of the design loop."""
    number: int
    timestamp: str
    source_code: str
    source_path: Optional[Path] = None
    render_result: Optional[RenderResult] = None
    notes: List[str] = field(default_factory=list)
    #: Measured facts the engine reported for this iteration (METADATA_KEYS).
    #: Persisted so the record, not a re-render, answers what each iteration
    #: measured; ``feature_effect`` compares consecutive records.
    metadata: Dict[str, Any] = field(default_factory=dict)
    #: Parameter overrides in force for this iteration.
    defines: Dict[str, str] = field(default_factory=dict)
    #: sha256 of the source text, to tell "the source changed" from "it did not".
    source_hash: str = ""
    #: The feature-effect report against the previous iteration.
    report: Optional[Report] = None
    _saved_image_paths: Dict[str, Path] = field(default_factory=dict)

    @property
    def image_paths(self) -> Dict[str, Path]:
        if self.render_result:
            return self.render_result.images
        return self._saved_image_paths

    def to_dict(self) -> Dict[str, Any]:
        return {
            "number": self.number,
            "timestamp": self.timestamp,
            "source_path": str(self.source_path) if self.source_path else None,
            "image_paths": {k: str(v) for k, v in self.image_paths.items()},
            "notes": list(self.notes),
            "metadata": dict(self.metadata),
            "defines": dict(self.defines),
            "source_hash": self.source_hash,
            "report": self.report.to_dict() if self.report else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Iteration":
        src = Path(data["source_path"]) if data.get("source_path") else None
        code = src.read_text() if src and src.exists() else ""
        rep_data = data.get("report")
        report = Report(lines=list(rep_data.get("lines", [])), warnings=list(rep_data.get("warnings", [])),
                        deltas=dict(rep_data.get("deltas", {})), changed=rep_data.get("changed")) if rep_data else None
        return cls(
            number=data["number"],
            timestamp=data["timestamp"],
            source_code=code,
            source_path=src,
            notes=list(data.get("notes", [])),
            metadata=dict(data.get("metadata") or {}),
            defines=dict(data.get("defines") or {}),
            source_hash=data.get("source_hash") or (source_hash(code) if code else ""),
            report=report,
            _saved_image_paths={k: Path(v) for k, v in (data.get("image_paths") or {}).items()},
        )


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class DesignSession:
    """Manages the full iteration lifecycle for a design.

    Args:
        name: Design name (used for project folder and filenames).
        engine: CAD engine to render with.
        config: Optional project config (for output paths, engine settings).
        max_iterations: Safety limit to prevent infinite loops.
        views: Camera views to render each iteration.
    """

    def __init__(
        self,
        name: str,
        engine: CADEngine,
        config: Optional[ProjectConfig] = None,
        max_iterations: int = 10,
        views: Optional[List[str]] = None,
        params: Optional[Dict[str, Any]] = None,
        defines: Optional[Dict[str, str]] = None,
    ):
        self.name = name
        self.engine = engine
        self.config = config or ProjectConfig()
        self.max_iterations = max_iterations
        self.views = views or self.config.output.default_views
        self.params = params or {}
        #: Model parameter overrides passed to every render and export.
        self.defines: Dict[str, str] = dict(defines or {})
        self.iterations: List[Iteration] = []
        self._finalized = False
        #: Meshes of part subprojects gathered by ``finalize --all``:
        #: (name, path, quantity), attached to the latest variant so the
        #: viewer shows the assembly with one toggle per part.
        self.part_meshes: List[tuple] = []

        # Set up project
        self.project = DesignProject(
            name, self.config.output,
            source_extension=engine.file_extension,
            syntax_language=engine.syntax_language,
        )
        self.project.metadata["engine"] = engine.name
        self.project.metadata["started"] = datetime.now().isoformat()
        self.project.setup()

        # Working directory for intermediate files
        self._work_dir = self.project.project_dir / "_work"
        self._work_dir.mkdir(exist_ok=True)

    @property
    def iteration_count(self) -> int:
        return len(self.iterations)

    @property
    def current(self) -> Optional[Iteration]:
        return self.iterations[-1] if self.iterations else None

    def iterate(self, source_code: str, defines: Optional[Dict[str, str]] = None) -> Iteration:
        """Submit new source code, render it, and record the iteration.

        ``defines`` are per-iteration overrides layered on the session's own;
        they are recorded on the iteration and do not change the session's.
        Returns the Iteration with render results and image paths.
        Raises RuntimeError if the session is finalized (``reopen()`` first)
        or max_iterations is exceeded.
        """
        if self._finalized:
            raise RuntimeError("Session already finalized; `agentcad session reopen` to continue it")
        effective = dict(self.defines)
        effective.update(defines or {})

        n = self.iteration_count + 1
        if n > self.max_iterations:
            raise RuntimeError(
                f"Max iterations ({self.max_iterations}) exceeded. "
                f"Call session.finalize() or increase max_iterations."
            )

        # Save source to work dir. Files already carrying this number belong
        # to a session the record does not know about (a restart before
        # archiving existed); they move aside rather than being overwritten,
        # so no export can later be mistaken for this iteration's.
        src_path = self._work_dir / f"{self.name}_v{n}{self.engine.file_extension}"
        render_dir = self._work_dir / f"v{n}"
        stale = [p for p in self._work_dir.glob(f"{self.name}_v{n}.*")] + ([render_dir] if render_dir.exists() else [])
        if stale:
            aside = self._work_dir / f"stale_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            aside.mkdir(exist_ok=True)
            for item in stale:
                shutil.move(str(item), str(aside / item.name))
            print(f"agentcad warning: v{n} files from an unrecorded session moved to {aside}", file=sys.stderr)
        src_path.write_text(source_code)
        render_dir.mkdir(exist_ok=True)
        render_result = self.engine.render(
            src_path, render_dir,
            views=self.views,
            image_size=self.config.output.image_size,
            defines=effective or None,
        )

        metadata = dict(render_result.metadata)
        if "volume" not in metadata and "stl" in self.engine.supported_export_formats:
            # An engine whose render carries no geometry (OpenSCAD renders
            # through its CLI) still measures through the mesh it exports.
            measured = self.engine.export(
                src_path, render_dir / f"{self.name}_v{n}_measure.stl", fmt="stl",
                defines=effective or None,
            )
            if measured.success:
                for key, value in measured.metadata.items():
                    metadata.setdefault(key, value)
            else:
                metadata["measure_error"] = "; ".join(measured.errors) or "STL export for measurement failed"

        previous = self.current
        digest = source_hash(source_code)
        report = feature_effect(
            previous.metadata if previous else None, metadata,
            source_changed=(digest != previous.source_hash) if previous and previous.source_hash else None,
            expected_solids=int(self.engine.setting("expected_solids")),
            short_edge_mm=float(self.engine.setting("short_edge_mm")),
        )

        iteration = Iteration(
            number=n,
            timestamp=datetime.now().isoformat(),
            source_code=source_code,
            source_path=src_path,
            render_result=render_result,
            metadata=metadata,
            defines=effective,
            source_hash=digest,
            report=report,
        )
        self.iterations.append(iteration)
        return iteration

    def reopen(self) -> None:
        """Continue a finalized session: numbering carries on, nothing is reset."""
        self._finalized = False
        self.project.metadata["reopened"] = datetime.now().isoformat()

    # --- tags ---------------------------------------------------------------

    @property
    def tags_dir(self) -> Path:
        return self.project.project_dir / "tags"

    @property
    def tags(self) -> Dict[str, Dict[str, Any]]:
        """Frozen iterations under ``tags/``: name -> TAG.json contents.

        Read from the folders every time rather than cached in the record,
        so a record written before a tag (or archived after one) never
        disagrees with what is on disk.
        """
        found: Dict[str, Dict[str, Any]] = {}
        if not self.tags_dir.exists():
            return found
        for tag_file in sorted(self.tags_dir.glob("*/TAG.json")):
            try:
                found[tag_file.parent.name] = json.loads(tag_file.read_text())
            except (OSError, json.JSONDecodeError) as e:
                print(f"agentcad warning: tag record unreadable, skipped: {tag_file}: {e}", file=sys.stderr)
        return found

    def tag(self, name: str, note: Optional[str] = None) -> Path:
        """Freeze the latest iteration under ``tags/<name>/`` for a review round.

        Copies its source, renders, metadata and any export into a folder laid
        out like a project (source/, renders/, exports/) so the viewer can be
        regenerated over it, and writes TAG.json. Refuses to overwrite an
        existing tag: a reviewer's reference must not move under them.
        """
        if not self.iterations:
            raise RuntimeError("No iteration to tag - call iterate() first")
        if not name or "/" in name or name.startswith("."):
            raise ValueError(f"tag name {name!r} must be a plain folder name")
        it = self.iterations[-1]
        dest = self.tags_dir / name
        if dest.exists():
            raise FileExistsError(f"tag {name!r} already exists at {dest}; tags are frozen")
        (dest / "source").mkdir(parents=True)
        (dest / "renders").mkdir()
        (dest / "exports").mkdir()
        stem = f"{self.name}_v{it.number}"
        (dest / "source" / f"{stem}{self.engine.file_extension}").write_text(it.source_code)
        for view, img in it.image_paths.items():
            if Path(img).exists():
                shutil.copy2(img, dest / "renders" / f"{stem}_{view}.png")
        exported = []
        for candidate in list(self.project.exports_dir.glob(f"{stem}.*")) + list(self._work_dir.glob(f"{stem}.*")):
            if candidate.suffix.lower() in (".stl", ".step", ".3mf", ".svg", ".off", ".amf"):
                target = dest / "exports" / candidate.name
                if not target.exists():
                    shutil.copy2(candidate, target)
                    exported.append(candidate.name)
        if not exported and "stl" in self.engine.supported_export_formats and it.source_path:
            result = self.engine.export(it.source_path, dest / "exports" / f"{stem}.stl", fmt="stl",
                                        defines=it.defines or None)
            if result.success:
                exported.append(f"{stem}.stl")
            else:
                print(f"agentcad warning: tag {name!r} has no mesh: {'; '.join(result.errors)}", file=sys.stderr)
        record = {
            "tag": name,
            "iteration": it.number,
            "timestamp": datetime.now().isoformat(),
            "source_hash": it.source_hash,
            "defines": dict(it.defines),
            "metadata": dict(it.metadata),
            "exports": exported,
            "note": note or "",
        }
        (dest / "TAG.json").write_text(json.dumps(record, indent=2, default=str))
        (dest / "agentcad.toml").write_text(
            f'[project]\nname = "{self.name}"\nengine = "{self.config.engine}"\n'
            f'description = "tag {name} of {self.name}: iteration {it.number}"\n'
        )
        return dest

    # --- archive --------------------------------------------------------------

    @classmethod
    def archive_previous(cls, project_name: str, config: Optional[ProjectConfig] = None,
                         reason: str = "") -> Optional[Path]:
        """Move an existing session record and its working files out of the way.

        ``session start -f`` used to overwrite session.json and restart
        numbering at v1, clobbering the earlier v1 files. Now the record and
        every ``_work/v*`` folder and ``_work/<name>_v*`` file move to
        ``_work/archive_<timestamp>/`` with a NOTE naming the reason. Returns
        the archive folder, or None when there was nothing to archive.
        """
        config = config or ProjectConfig()
        work = config.output.designs_dir / project_name / "_work"
        state = work / SESSION_STATE_FILE
        if not state.exists():
            return None
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive = work / f"archive_{stamp}"
        n = 1
        while archive.exists():
            n += 1
            archive = work / f"archive_{stamp}_{n}"
        archive.mkdir(parents=True)
        shutil.move(str(state), str(archive / SESSION_STATE_FILE))
        for item in sorted(work.iterdir()):
            if item.name.startswith("archive_") or item == archive:
                continue
            if (item.is_dir() and item.name.startswith("v")) or item.name.startswith(f"{project_name}_v"):
                shutil.move(str(item), str(archive / item.name))
        (archive / "NOTE.txt").write_text(
            f"Archived {datetime.now().isoformat()} before a new session start.\n"
            f"Reason: {reason or 'session start --force'}\n"
        )
        return archive

    def note(self, text: str) -> None:
        """Add an analysis note to the current iteration."""
        if not self.iterations:
            raise RuntimeError("No iteration to annotate - call iterate() first")
        self.iterations[-1].notes.append(text)

    def finalize(self, export_all: bool = False) -> Path:
        """Export all iterations as variants, generate HTML viewer with version history.

        Idempotent: a second call rebuilds the variant list from the
        iterations rather than duplicating it, and exports only iterations
        that have no export yet unless ``export_all``. Returns the path to
        the generated index.html.
        """
        if not self.iterations:
            raise RuntimeError("No iterations to finalize")

        self._finalized = True
        self.project.variants.clear()

        # Register EVERY iteration as a variant (latest first)
        for it in reversed(self.iterations):
            label = f"v{it.number}"
            if it is self.iterations[-1]:
                label += " (latest)"

            variant_params = dict(self.params)
            variant_params["iteration"] = it.number
            variant_params["timestamp"] = it.timestamp
            if it.notes:
                variant_params["notes"] = "\n".join(it.notes)

            variant = self.project.add_variant(label, variant_params)
            variant.source_code = it.source_code
            variant.source_path = it.source_path

            # Save source
            self.project.save_source(
                variant, it.source_code,
                filename=f"{self.name}_v{it.number}{self.engine.file_extension}",
            )

            # Register renders
            for view, img_path in it.image_paths.items():
                self.project.register_render(
                    variant, view, img_path,
                    filename=f"{self.name}_v{it.number}_{view}.png",
                )

            # Export STL for each iteration (the viewer's 3D tab reads STL);
            # an export already on disk is reused unless export_all.
            stl_path = self._work_dir / f"{self.name}_v{it.number}.stl"
            existing = self.project.exports_dir / f"{self.name}_v{it.number}.stl"
            src_mtime = it.source_path.stat().st_mtime if it.source_path and it.source_path.exists() else 0.0
            if existing.exists() and not export_all and existing.stat().st_mtime >= src_mtime:
                # an export at least as new as its source is the same geometry
                variant.stl_path = existing
                self._attach_part_meshes(variant, it)
                continue
            stl_result = self.engine.export(
                it.source_path, stl_path, fmt="stl", defines=it.defines or self.defines or None,
            )
            if stl_result.success:
                self.project.register_stl(
                    variant, stl_result.output_path,
                    filename=f"{self.name}_v{it.number}.stl",
                )
                self._attach_part_meshes(variant, it)
            else:
                for err in stl_result.errors:
                    print(f"agentcad warning: v{it.number} STL export failed (viewer without mesh): {err}",
                          file=sys.stderr)

        # Generate print manifest for final iteration
        from agentcad.manifest import PrintManifest
        manifest = PrintManifest(
            part_name=self.name,
            project_name=self.project.name,
            stl_filename=f"{self.name}_v{self.iterations[-1].number}.stl",
            design_iterations=self.iteration_count,
            engine=self.engine.name,
            agent_notes=[n for it in self.iterations for n in it.notes],
        )
        # Apply any print params from session
        for k in ("material", "layer_height", "infill_percent", "supports",
                   "print_orientation", "printer_profile"):
            if k in self.params:
                setattr(manifest, k, self.params[k])
        manifest.parts = ([{"name": name, "quantity": int(quantity), "stl_filename": Path(path).name}
                           for name, path, quantity in self.part_meshes]
                          or [{"name": self.name, "quantity": 1, "stl_filename": manifest.stl_filename}])
        manifest_path = self.project.exports_dir / f"{self.name}.print.json"
        if manifest_path.exists():
            try:
                manifest.fit = PrintManifest.load(manifest_path).fit   # fit results recorded earlier survive a re-finalize
            except (OSError, ValueError, TypeError, KeyError):
                pass

        manifest.save(manifest_path)
        self.project.metadata["manifest"] = str(manifest_path.name)

        # Add session metadata
        self.project.metadata["iterations"] = self.iteration_count
        self.project.metadata["finalized"] = datetime.now().isoformat()

        # Store manifest on project for viewer access
        self.project._manifest = manifest

        # Generate HTML viewer
        return self.project.generate_viewer()

    def _attach_part_meshes(self, variant, it: Iteration) -> None:
        """On the latest variant, replace the assembly's own mesh with the parts' meshes."""
        if not self.part_meshes or it is not self.iterations[-1]:
            return
        variant.meshes = []
        for name, path, quantity in self.part_meshes:
            variant.add_mesh(name, Path(path), quantity=quantity)

    def summary(self) -> str:
        """Human-readable session summary."""
        lines = [f"DesignSession: {self.name}"]
        lines.append(f"  Engine: {self.engine.name}")
        lines.append(f"  Iterations: {self.iteration_count}/{self.max_iterations}")
        for it in self.iterations:
            status = "OK" if (it.render_result and it.render_result.success) or it.image_paths else "?"
            notes_count = len(it.notes)
            lines.append(f"  v{it.number}: [{status}] {notes_count} note(s)")
            for note in it.notes:
                lines.append(f"    - {note}")
        if self._finalized:
            lines.append(f"  Finalized: {self.project.project_dir}")
        return "\n".join(lines)

    @property
    def state_file(self) -> Path:
        return self._work_dir / SESSION_STATE_FILE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": SESSION_SCHEMA,
            "name": self.name,
            "engine_name": self.engine.name,
            "max_iterations": self.max_iterations,
            "views": list(self.views),
            "params": dict(self.params),
            "defines": dict(self.defines),
            "finalized": self._finalized,
            "project_metadata": dict(self.project.metadata),
            "tags": dict(self.tags),
            "iterations": [it.to_dict() for it in self.iterations],
        }

    def save_state(self) -> Path:
        """Persist session state to {project_dir}/_work/session.json."""
        self._work_dir.mkdir(parents=True, exist_ok=True)
        path = self.state_file
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path

    @classmethod
    def load_state(
        cls,
        project_name: str,
        engine: CADEngine,
        config: Optional[ProjectConfig] = None,
    ) -> "DesignSession":
        """Reconstruct a session from {project_dir}/_work/session.json.

        Args:
            project_name: Project folder name (becomes session name).
            engine: Reconstructed engine (caller provides via get_engine()).
            config: Project config (defaults to fresh ProjectConfig()).
        """
        config = config or ProjectConfig()
        project_dir = config.output.designs_dir / project_name
        state_path = project_dir / "_work" / SESSION_STATE_FILE
        if not state_path.exists():
            raise FileNotFoundError(
                f"No session state at {state_path}. Run `agentcad session start {project_name}` first."
            )

        data = json.loads(state_path.read_text())

        # Sanity: engine match
        if data.get("engine_name") and data["engine_name"] != engine.name:
            raise ValueError(
                f"Session was started with engine '{data['engine_name']}' "
                f"but loaded engine is '{engine.name}'."
            )

        session = cls(
            name=data["name"],
            engine=engine,
            config=config,
            max_iterations=data.get("max_iterations", 10),
            views=data.get("views"),
            params=data.get("params") or {},
            defines=data.get("defines") or {},
        )
        session._finalized = data.get("finalized", False)
        for meta_k, meta_v in (data.get("project_metadata") or {}).items():
            session.project.metadata.setdefault(meta_k, meta_v)
        for it_data in data.get("iterations", []):
            session.iterations.append(Iteration.from_dict(it_data))
        return session
