"""Measured facts from a triangle mesh file.

Engines whose kernels do not expose geometry (OpenSCAD renders through its
CLI) still produce an STL, and an STL carries enough to fill the report's
tray: the bounding box, the enclosed volume (signed sum of tetrahedra, so a
consistently wound mesh reports the true volume) and the number of
connected bodies, which is the connectivity gate a render cannot be.

Every measurement is best effort: a missing dependency or an unreadable
file becomes a ``<key>_error`` entry, never an exception, so a failed
measurement cannot fail the export that produced the mesh.
"""

import struct
from pathlib import Path
from typing import Any, Dict, Tuple


def read_stl(path: Path) -> Tuple["Any", "Any"]:
    """Vertices (N, 3) and triangle index rows (M, 3) from a binary or ASCII STL."""
    import numpy as np

    data = Path(path).read_bytes()
    if data[:5] == b"solid" and b"vertex" in data[:4096] and not _looks_binary(data):
        pts = []
        for line in data.decode("ascii", errors="replace").splitlines():
            parts = line.split()
            if len(parts) == 4 and parts[0] == "vertex":
                pts.append([float(parts[1]), float(parts[2]), float(parts[3])])
        V = np.array(pts, dtype=np.float64).reshape(-1, 3)
    else:
        count = struct.unpack_from("<I", data, 80)[0]
        rec = np.frombuffer(data, dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]), count=count, offset=84)
        V = rec["v"].astype(np.float64).reshape(-1, 3)
    F = np.arange(len(V)).reshape(-1, 3)
    return V, F


def _looks_binary(data: bytes) -> bool:
    if len(data) < 84:
        return False
    count = struct.unpack_from("<I", data, 80)[0]
    return len(data) == 84 + 50 * count


def measure_stl(path: Path) -> Dict[str, Any]:
    """bbox_min, bbox_size, volume, facet_count and counts.solids of an STL file."""
    md: Dict[str, Any] = {}
    try:
        import numpy as np
        V, F = read_stl(path)
    except ImportError as e:
        md["mesh_error"] = f"numpy unavailable: {e}"
        return md
    except (OSError, ValueError, struct.error) as e:
        md["mesh_error"] = f"unreadable STL: {e}"
        return md
    if len(V) == 0:
        md["mesh_error"] = "empty mesh"
        return md

    md["facet_count"] = int(len(F))
    lo, hi = V.min(axis=0), V.max(axis=0)
    md["bbox_min"] = [float(v) for v in lo]
    md["bbox_size"] = [float(v) for v in hi - lo]

    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    md["volume"] = float(abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0)

    try:
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        # Merge coincident vertices (STL repeats them per triangle) by
        # quantising to a fraction of the bounding box, then count the
        # connected components of the triangle-vertex graph.
        scale = max(float((hi - lo).max()), 1e-9) * 1e-7
        keys = np.round(V / scale).astype(np.int64)
        _, inv = np.unique(keys, axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        tri = inv.reshape(-1, 3)
        rows = np.concatenate([tri[:, 0], tri[:, 1], tri[:, 2]])
        cols = np.concatenate([tri[:, 1], tri[:, 2], tri[:, 0]])
        n = int(inv.max()) + 1
        graph = coo_matrix((np.ones(len(rows), dtype=np.int8), (rows, cols)), shape=(n, n))
        count, _ = connected_components(graph, directed=False)
        md["counts"] = {"solids": int(count)}
    except ImportError as e:
        md["counts_error"] = f"scipy unavailable for connectivity: {e}"
    except (ValueError, MemoryError) as e:
        md["counts_error"] = f"connectivity failed: {e}"
    return md
