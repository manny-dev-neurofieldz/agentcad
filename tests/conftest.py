"""Shared fixtures for the agentcad test suite.

Engine tests are parametrized over the registry and skip when a backend is
not installed, so the suite is green on a machine with only one engine and
still exercises every engine that is present.
"""

import struct
from pathlib import Path
from typing import Dict, Tuple

import pytest

from agentcad.engines import get_engine, list_engines

# One minimal parametric source per engine. Each takes a `size` parameter so
# the contract test can prove that `-D size=...` reaches the model.
SOURCES: Dict[str, str] = {
    "openscad": "size = 10;\ncube(size);\n",
    "voxelcad": (
        "from voxelcad import Cube\n"
        "\n"
        "def build(size=10):\n"
        "    return Cube(size=size)\n"
    ),
    "build123d": (
        "from build123d import Box\n"
        "\n"
        "def build(size=10):\n"
        "    return Box(size, size, size)\n"
    ),
}

BAD_SOURCES: Dict[str, str] = {
    "openscad": "cube(10;\n",
    "voxelcad": "def build(:\n",
    "build123d": "def build(:\n",
}


@pytest.fixture(params=list_engines())
def engine_name(request) -> str:
    """Every registered engine name, one per parametrized case."""
    return request.param


@pytest.fixture
def engine(engine_name):
    """A constructed engine whose backend is present, else the case is skipped."""
    eng = get_engine(engine_name)
    if not eng.available():
        pytest.skip(f"{eng.name} backend not available")
    if engine_name not in SOURCES:
        pytest.skip(f"no fixture source for engine '{engine_name}'")
    return eng


@pytest.fixture
def source_file(engine, engine_name, tmp_path) -> Path:
    """The engine's fixture source written to a temp file with its extension."""
    path = tmp_path / f"fixture{engine.file_extension}"
    path.write_text(SOURCES[engine_name])
    return path


def stl_bbox(path: Path) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """Axis-aligned bounding box of an STL file (binary or ASCII)."""
    data = path.read_bytes()
    mins = [float("inf")] * 3
    maxs = [float("-inf")] * 3

    def take(v):
        for i in range(3):
            mins[i] = min(mins[i], v[i])
            maxs[i] = max(maxs[i], v[i])

    if data[:5] == b"solid" and b"vertex" in data[:2048]:
        for line in data.decode("ascii", errors="replace").splitlines():
            parts = line.split()
            if len(parts) == 4 and parts[0] == "vertex":
                take(tuple(float(p) for p in parts[1:]))
    else:
        count = struct.unpack_from("<I", data, 80)[0]
        offset = 84
        for _ in range(count):
            rec = struct.unpack_from("<12fH", data, offset)
            take(rec[3:6])
            take(rec[6:9])
            take(rec[9:12])
            offset += 50
    return tuple(mins), tuple(maxs)


def stl_extent(path: Path) -> Tuple[float, float, float]:
    mins, maxs = stl_bbox(path)
    return tuple(maxs[i] - mins[i] for i in range(3))
