"""Run an engine's worker module in a subprocess with a timeout.

Engines whose kernels can hang or exhaust memory (build123d's OCCT, VoxelCAD's
voxel grids) execute the user's source in a worker process rather than in the
CLI. The protocol is one job file in, one result file out:

* the engine writes ``job`` (a JSON-serialisable dict) to a temp file and
  adds ``result_path`` to it;
* the worker module is run as ``python -m <module> JOB_JSON`` and writes the
  result JSON to ``result_path``, turning every failure into an ``errors``
  entry rather than an exit status;
* a timeout, a crash before the result is written, or an unreadable result
  each come back as a result dict with ``errors`` filled, so the caller never
  sees an exception.

Shared by every subprocess-hosted engine so the timeout and failure
semantics are the same across them.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional


def failed(message: str) -> Dict[str, Any]:
    """An empty result record carrying one error."""
    return {"errors": [message], "warnings": [], "images": {}, "output_path": None,
            "facet_count": 0, "metadata": {}}


def run_worker(module: str, job: Dict[str, Any], timeout: float, *,
               label: str, cwd: Optional[Path] = None) -> Dict[str, Any]:
    """Run ``module`` on ``job``; always returns a result dict (errors filled on failure).

    ``label`` names the engine in messages ("build123d worker timed out after 120s").
    """
    with tempfile.TemporaryDirectory(prefix=f"agentcad_{label}_") as tmp:
        job_path = Path(tmp) / "job.json"
        result_path = Path(tmp) / "result.json"
        job["result_path"] = str(result_path)
        job_path.write_text(json.dumps(job))
        cmd = [sys.executable, "-m", module, str(job_path)]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                cwd=str(cwd) if cwd else None, env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired:
            return failed(f"{label} worker timed out after {timeout:g}s")
        if result_path.exists():
            try:
                return json.loads(result_path.read_text())
            except json.JSONDecodeError as e:
                return failed(f"worker result unreadable: {e}")
        tail = (proc.stderr or "").strip().splitlines()
        detail = tail[-1] if tail else f"exit status {proc.returncode}"
        return failed(f"{label} worker produced no result: {detail}")
