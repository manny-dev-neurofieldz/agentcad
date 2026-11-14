"""examples/build_walkthroughs.py: runs the walkthroughs and keeps their pictures true.

The script is a plain file under examples/ (not a package), loaded here by path. Walkthroughs are written into
tmp_path and the builder is pointed at them with --root and --images, so these tests never touch examples/'s
own walkthroughs or docs/images/.
"""
import importlib.util
from pathlib import Path

import pytest
from PIL import Image

from agentcad.engines import get_engine

SCRIPT = Path(__file__).resolve().parents[1] / "examples" / "build_walkthroughs.py"
spec = importlib.util.spec_from_file_location("build_walkthroughs", SCRIPT)
bw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bw)

needs_openscad = pytest.mark.skipif(not get_engine("openscad").available(), reason="OpenSCAD is not installed here")

IMAGE = "examples/hex_tray/_work/v1/hex_tray_v1_iso.png"
TINY = f"""# Tiny

Start a session, iterate once, keep the picture.

```console
# recipe: examples
$ agentcad session start examples/hex_tray
Session started for project 'hex_tray'
$ agentcad session iterate examples/hex_tray examples/hex_tray/source/hex_tray.scad
Iteration v1 recorded
# image: {IMAGE} -> v1_iso.png
```
"""


@pytest.fixture
def tree(tmp_path):
    """(root with a walkthrough folder, images folder, write(text))."""
    root, images = tmp_path / "walks", tmp_path / "images"
    (root / "tiny").mkdir(parents=True)

    def write(text, name="tiny"):
        (root / name).mkdir(exist_ok=True)
        (root / name / "WALKTHROUGH.md").write_text(text)
    return root, images, write


def run(root, images, *extra):
    return bw.main(["--root", str(root), "--images", str(images), *extra])


@needs_openscad
def test_a_walkthrough_builds_and_writes_a_small_picture(tree, capsys):
    root, images, write = tree
    write(TINY)
    assert run(root, images) == 0
    out = capsys.readouterr().out
    png = images / "tiny" / "v1_iso.png"
    assert png.is_file() and "v1_iso.png" in out
    assert max(Image.open(png).size) <= 768
    assert png.stat().st_size < 150_000


@needs_openscad
def test_each_block_runs_in_a_workspace_of_its_own(tree, capsys):
    """A second block repeats `session start`; in a shared workspace that would be refused."""
    root, images, write = tree
    block = TINY.split("```console\n")[1].split("```")[0]
    write("```console\n" + block + "```\n\nAgain, from scratch:\n\n```console\n" + block.replace("-> v1_iso", "-> again")
          + "```\n")
    assert run(root, images) == 0
    assert (images / "tiny" / "v1_iso.png").is_file() and (images / "tiny" / "again.png").is_file()
    assert "2 block(s)" in capsys.readouterr().out


@needs_openscad
def test_verify_fails_on_a_missing_picture_and_passes_when_it_is_there(tree, capsys):
    root, images, write = tree
    write(TINY)
    assert run(root, images, "--verify") == 1
    assert "v1_iso.png" in capsys.readouterr().err
    (images / "tiny").mkdir(parents=True)
    Image.new("RGB", (4, 4)).save(images / "tiny" / "v1_iso.png")
    assert run(root, images, "--verify") == 0


@needs_openscad
def test_a_step_that_does_not_show_what_the_text_says_fails_naming_file_and_line(tree, capsys):
    root, images, write = tree
    write(TINY.replace("Iteration v1 recorded", "Iteration v9 recorded"))
    assert run(root, images) == 1
    err = capsys.readouterr().err
    assert "WALKTHROUGH.md:" in err and "Iteration v9 recorded" in err and "session iterate" in err


@needs_openscad
def test_an_image_the_step_did_not_produce_is_named(tree, capsys):
    root, images, write = tree
    write(TINY.replace("hex_tray_v1_iso.png", "no_such.png"))
    assert run(root, images) == 1
    assert "did not produce" in capsys.readouterr().err


def test_an_image_line_before_any_step_is_refused(tree, capsys):
    root, images, write = tree
    write("```console\n# recipe: empty\n# image: a.png -> b.png\n$ agentcad info\nagentcad\n```\n")
    assert run(root, images) == 1
    assert "under a step" in capsys.readouterr().err


@pytest.mark.parametrize("dest", ["../escape.png", "/abs/escape.png", "a/../../b.png"])
def test_a_destination_that_escapes_the_images_folder_is_refused(tree, capsys, dest):
    root, images, write = tree
    write(f"```console\n# recipe: empty\n$ agentcad info\nagentcad\n# image: a.png -> {dest}\n```\n")
    assert run(root, images) == 1
    assert "leaves docs/images/tiny" in capsys.readouterr().err
    assert not (images.parent / "escape.png").exists()


def test_a_walkthrough_with_no_recipe_block_is_refused(tree, capsys):
    root, images, write = tree
    write("# Prose only\n\n```console\n$ agentcad info\n```\n")
    assert run(root, images) == 1
    assert "no recipe block" in capsys.readouterr().err


def test_a_walkthrough_whose_engine_is_missing_is_skipped_unless_strict(tree, capsys, monkeypatch):
    root, images, write = tree
    write(TINY)
    monkeypatch.setattr(bw, "missing_engines", lambda wt: ["openscad"])
    assert run(root, images) == 0
    assert "skip tiny" in capsys.readouterr().out
    assert run(root, images, "--verify") == 0
    monkeypatch.setenv("AGENTCAD_DOCS_STRICT", "1")
    assert run(root, images, "--verify") == 1
    assert "not installed" in capsys.readouterr().err
    assert run(root, images) == 0, "building still skips: strict is a verify rule"


def test_a_python_engine_without_pyvista_is_skipped_with_that_reason(tree, capsys, monkeypatch):
    root, images, write = tree
    write(TINY)
    monkeypatch.setattr(bw, "_engines_named", lambda wt: ["voxelcad"])
    monkeypatch.setattr(bw, "missing_engines", lambda wt: [])
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "pyvista" else real(name, *a))
    assert run(root, images, "--verify") == 0
    assert "skip tiny: engine voxelcad renders with PyVista, which is not installed here" in capsys.readouterr().out
    monkeypatch.setenv("AGENTCAD_DOCS_STRICT", "1")
    assert run(root, images, "--verify") == 1
    assert "PyVista" in capsys.readouterr().err


def test_only_names_a_walkthrough_and_an_unknown_name_is_an_error(tree):
    root, images, write = tree
    write("# nothing\n")
    with pytest.raises(SystemExit, match="nope"):
        run(root, images, "--only", "nope")


def _gradient(rng, amp, size=(1200, 1600)):
    """A smooth colour ramp with a little noise: big as plain PNG, small once reduced to a palette."""
    import numpy as np

    h, w = size
    g = np.add.outer(np.linspace(0, 127, h), np.linspace(0, 127, w))
    a = np.stack([g, g[::-1], g[:, ::-1]], -1) + rng.normal(0, amp, (h, w, 3))
    return Image.fromarray(a.clip(0, 255).astype("uint8"))


def test_a_large_picture_is_scaled_to_768_and_kept_under_the_limit(tmp_path):
    import numpy as np

    src = tmp_path / "big.png"
    _gradient(np.random.default_rng(1), 2).save(src)
    dest = tmp_path / "out" / "big.png"
    note = bw.save_image(src, dest)
    assert max(Image.open(dest).size) <= 768 and dest.stat().st_size < 150_000
    assert "256 colours" in note, "this ramp only fits under the limit as a palette"


def test_a_picture_that_cannot_fit_is_refused_by_name(tmp_path):
    import numpy as np

    src = tmp_path / "noise.png"
    Image.fromarray(np.random.default_rng(1).integers(0, 255, (900, 900, 3), dtype="uint8")).save(src)
    with pytest.raises(bw.WalkthroughError, match="noise.png"):
        bw.save_image(src, tmp_path / "noise.png.out" / "noise.png")
