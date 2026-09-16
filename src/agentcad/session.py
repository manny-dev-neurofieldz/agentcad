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

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agentcad.config import OutputConfig, ProjectConfig
from agentcad.engine import CADEngine, RenderResult
from agentcad.output import DesignProject

SESSION_STATE_FILE = "session.json"


@dataclass
class Iteration:
    """One iteration of the design loop."""
    number: int
    timestamp: str
    source_code: str
    source_path: Optional[Path] = None
    render_result: Optional[RenderResult] = None
    notes: List[str] = field(default_factory=list)
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
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Iteration":
        src = Path(data["source_path"]) if data.get("source_path") else None
        code = src.read_text() if src and src.exists() else ""
        return cls(
            number=data["number"],
            timestamp=data["timestamp"],
            source_code=code,
            source_path=src,
            notes=list(data.get("notes", [])),
            _saved_image_paths={k: Path(v) for k, v in (data.get("image_paths") or {}).items()},
        )


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

    def iterate(self, source_code: str) -> Iteration:
        """Submit new source code, render it, and record the iteration.

        Returns the Iteration with render results and image paths.
        Raises RuntimeError if max_iterations exceeded.
        """
        if self._finalized:
            raise RuntimeError("Session already finalized")

        n = self.iteration_count + 1
        if n > self.max_iterations:
            raise RuntimeError(
                f"Max iterations ({self.max_iterations}) exceeded. "
                f"Call session.finalize() or increase max_iterations."
            )

        # Save source to work dir
        src_path = self._work_dir / f"{self.name}_v{n}{self.engine.file_extension}"
        src_path.write_text(source_code)

        # Render
        render_dir = self._work_dir / f"v{n}"
        render_dir.mkdir(exist_ok=True)
        render_result = self.engine.render(
            src_path, render_dir,
            views=self.views,
            image_size=self.config.output.image_size,
            defines=self.defines or None,
        )

        iteration = Iteration(
            number=n,
            timestamp=datetime.now().isoformat(),
            source_code=source_code,
            source_path=src_path,
            render_result=render_result,
        )
        self.iterations.append(iteration)
        return iteration

    def note(self, text: str) -> None:
        """Add an analysis note to the current iteration."""
        if not self.iterations:
            raise RuntimeError("No iteration to annotate - call iterate() first")
        self.iterations[-1].notes.append(text)

    def finalize(self) -> Path:
        """Export all iterations as variants, generate HTML viewer with version history.

        Returns path to the generated index.html.
        """
        if not self.iterations:
            raise RuntimeError("No iterations to finalize")

        self._finalized = True

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

            # Export STL for each iteration (the viewer's 3D tab reads STL)
            stl_path = self._work_dir / f"{self.name}_v{it.number}.stl"
            stl_result = self.engine.export(
                it.source_path, stl_path, fmt="stl", defines=self.defines or None,
            )
            if stl_result.success:
                self.project.register_stl(
                    variant, stl_result.output_path,
                    filename=f"{self.name}_v{it.number}.stl",
                )
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

        manifest_path = self.project.exports_dir / f"{self.name}.print.json"
        manifest.save(manifest_path)
        self.project.metadata["manifest"] = str(manifest_path.name)

        # Add session metadata
        self.project.metadata["iterations"] = self.iteration_count
        self.project.metadata["finalized"] = datetime.now().isoformat()

        # Store manifest on project for viewer access
        self.project._manifest = manifest

        # Generate HTML viewer
        return self.project.generate_viewer()

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
            "name": self.name,
            "engine_name": self.engine.name,
            "max_iterations": self.max_iterations,
            "views": list(self.views),
            "params": dict(self.params),
            "defines": dict(self.defines),
            "finalized": self._finalized,
            "project_metadata": dict(self.project.metadata),
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
