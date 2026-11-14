"""The recipes in the policies run: each ``console`` block marked ``# recipe:`` is a sequence of agentcad commands
with the output it must show, executed here against a scratch copy of the examples. A policy's worked example is
then a tested claim, and a change that breaks one fails here, in the same pull request.

A recipe whose engine is not installed is skipped with the engine named (``-rs`` lists them); CI installs all
three, so there every recipe runs.
"""
import shutil
from pathlib import Path

import pytest

from agentcad import policy as pol
from agentcad.engines import get_engine
from tests.gcode_fixtures import run_cli

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
RECIPES = [r for p in pol.all_policies() for r in pol.recipes(p)]
#: Generated folders an example may hold in a working checkout; a recipe starts without them.
GENERATED = ("_work", "exports", "renders", "viewer", "_archive", "__pycache__")


def _missing(engine):
    """Why an engine cannot run a recipe here, or None. The Python engines also need PyVista to render, which
    their availability check does not ask for."""
    import importlib.util

    if not get_engine(engine).available():
        return f"engine {engine} is not installed here"
    if engine in ("build123d", "voxelcad") and importlib.util.find_spec("pyvista") is None:
        return f"engine {engine} renders with PyVista, which is not installed here"
    return None


def _engines_named(recipe):
    """The engines a recipe's examples use, read from their project files."""
    from agentcad.config import find_project

    names = set()
    for step in recipe.steps:
        for word in step.argv:
            if word.startswith("examples/"):
                project = find_project(EXAMPLES / Path(word).relative_to("examples").parts[0])
                if project is not None:
                    names.add(project.engine)
    return names


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A scratch folder to run in, with a user config folder of its own: a step never reads the developer's
    printers or targets. (HOME stays: the engines' workers find their packages through it.)"""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    def make(kind):
        if kind == "examples":
            shutil.copytree(EXAMPLES, tmp_path / "examples", ignore=shutil.ignore_patterns(*GENERATED))
        monkeypatch.chdir(tmp_path)
        return tmp_path
    return make


def test_the_policies_carry_recipes():
    assert len(RECIPES) >= 6, "the upgraded policies' recipes are found"


@pytest.mark.parametrize("recipe", RECIPES, ids=[f"{r.policy}:{r.line}" for r in RECIPES])
def test_a_recipe_runs_and_shows_what_it_says(recipe, workspace, capsys):
    for name in sorted(_engines_named(recipe)):
        if _missing(name):
            pytest.skip(_missing(name))
    workspace(recipe.workspace)
    for step in recipe.steps:
        rc, out, err = run_cli(capsys, *step.argv)
        said = f"agentcad {' '.join(step.argv)} (in {recipe.policy}, recipe at line {recipe.line})"
        assert rc == step.exit, f"{said} ended with {rc}, the recipe says {step.exit}:\n{out}\n{err}"
        missing = pol.expect_matches(step.expect, out + "\n" + err)
        assert missing is None, f"{said} did not show {missing!r}:\n{out}\n{err}"


@pytest.mark.parametrize("body, said", [
    ("# recipe: garden\n$ agentcad info\nx", "workspace 'garden'"),
    ("# recipe: empty\n$ ls\nx", "runs agentcad"),
    ("# recipe: empty\noutput first\n$ agentcad info", "output before the first step"),
    ("# recipe: empty\n# only a comment", "no step"),
    ("# recipe: empty\n$ agentcad info\n# exit 0", "expects no output"),
    ("# recipe: empty\n$ agentcad info\n...", "only '...'"),
    ("# recipe: empty\n$ agentcad info\n# exit two\nx", "takes a number"),
])
def test_a_malformed_recipe_is_refused_by_policy_and_line(body, said):
    text = f"# T\n\n```console\n{body}\n```\n"
    with pytest.raises(pol.PolicyError, match=said):
        pol.recipes(pol.Policy("agentcad-x", text, {}))


def test_a_recipe_under_another_fence_is_refused_not_skipped():
    text = "# T\n\n```sh\n# recipe: empty\n$ agentcad info\nRegistered\n```\n"
    with pytest.raises(pol.PolicyError, match="a recipe goes in a `console` fence"):
        pol.recipes(pol.Policy("agentcad-x", text, {}))


def test_expected_lines_match_in_order_with_dots_for_any_text():
    out = "staged 2 part(s)\n  /tmp/a/asm.3mf\nnote: the bed differs"
    assert pol.expect_matches(["staged 2 part(s)", "asm.3mf", "note: ... differs"], out) is None
    assert pol.expect_matches(["note:", "staged"], out) == "staged", "order matters"
    assert pol.expect_matches(["staged 3"], out) == "staged 3"
