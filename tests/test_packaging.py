"""The wheel carries the package's data, not only its modules.

Editable installs (CI's and the README's) read the templates straight from the
source tree, so a wheel missing them goes unnoticed until a viewer or a
toolpath page is built from a regular install. This builds a wheel from a copy
of the source (the checkout stays clean) and looks inside it.
"""

import shutil
import subprocess
import sys
import zipfile

import pytest


@pytest.fixture(scope="module")
def wheel_files(tmp_path_factory, pytestconfig):
    root = pytestconfig.rootpath
    src = tmp_path_factory.mktemp("source")
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        if (root / name).exists():
            shutil.copy2(root / name, src / name)
    shutil.copytree(root / "src", src / "src",
                    ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "*.so", "build"))
    out = tmp_path_factory.mktemp("wheel")
    proc = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                           "-q", "-w", str(out), str(src)], capture_output=True, text=True)
    if proc.returncode:
        pytest.fail(f"pip wheel failed:\n{proc.stderr[-2000:]}")
    wheels = sorted(out.glob("agentcad-*.whl"))
    assert len(wheels) == 1, wheels
    with zipfile.ZipFile(wheels[0]) as z:
        return set(z.namelist())


@pytest.mark.parametrize("name", [
    "agentcad/templates/viewer.html",
    "agentcad/templates/variant.html",
    "agentcad/templates/vendor/three.min.js",
    "agentcad/templates/vendor/OrbitControls.js",
    "agentcad/templates/vendor/STLLoader.js",
    "agentcad/templates/vendor/hljs-openscad.min.js",
    "agentcad/policies/agentcad-policies.md",
    "agentcad/policies/agentcad-session.md",
    "agentcad/policies/agentcad-gcode.md",
])
def test_the_wheel_carries_the_viewer_templates(wheel_files, name):
    assert name in wheel_files, f"{name} is missing from the wheel"


def test_the_wheel_carries_the_command_modules_package(wheel_files):
    assert "agentcad/commands/__init__.py" in wheel_files
