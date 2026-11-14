# Plugin Export: agentcad's Know-How Written Out for an Agent Harness

**Type**: Capability Policy (distribution)
**Scope**: Any agent or person making agentcad's skills and reviewer agent available in an agent harness
**Status**: ACTIVE
**Commands**: agentcad plugin export, agentcad plugin hook

## Purpose

agentcad ships its know-how in the package: policies read through `agentcad policy`, skills that walk a workflow, and a reviewer agent. A harness finds skills and agents only where it looks for them. `agentcad plugin export` writes that know-how out in a harness's own layout, so a session with no memory of agentcad can run its workflows: a plugin for Claude Code, a policy root for the MacEff framework (https://github.com/cversek/MacEff), an `AGENTS.md`, or tool definitions for a model API. Every target is generated from one bundle of the package's commands, policies, skills, reviewer agent and hooks, so the targets cannot disagree about what agentcad is. This policy says what the export holds, what its hooks tell or refuse a session, what it leaves to the installed command, and how to check it.

## CEP Navigation Guide

**1 What an Export Holds**
- Which files does an export write, and where do they come from?
- What does an export never hold?

**1.1 The Other Targets**
- What does the policy root for MacEff hold, and which folder is mounted?
- What does the AGENTS.md carry of a policy, and what does it leave in the command?
- How does a tool call become a command line?

**2 Exporting**
- Which targets are there, and what does each flag do?
- What happens to the folder written into?
- When is an export refused?

**3 Checking and Using It**
- How is an export checked before it is used?
- What must be true where the plugin is used?

**4 The Hooks**
- What does each hook tell a session, and when does it say nothing?
- Which edits does the library guard refuse, and how does a library declare them?
- What does the guard not see?
- What happens where the agentcad command is missing or at another version?

**5 Integration with Other Policies**
- Which policies do the exported skills read?

**6 Anti-Patterns**
- Which uses of an export defeat it?

**7 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 What an Export Holds

For the `claude-code` target an export writes:

- `.claude-plugin/plugin.json`: the plugin's name (`agentcad`), its version (the package's own), and the description, author and license from the package's metadata;
- `skills/<name>/SKILL.md` for each skill the package ships, invoked in the harness as `/agentcad:<name>`;
- `agents/design-reviewer.md`, the reviewer agent, named `agentcad:design-reviewer` there;
- `hooks/hooks.json` and `hooks/run.sh`: three hooks (section 4) and the runner that hands each to the installed command;
- with `--marketplace`, `.claude-plugin/marketplace.json`: a local marketplace offering the plugin from the same folder.

An export holds no agentcad code, no permission rule and no server; its one script, the runner, only calls the installed command. The skills call the `agentcad` command and read its policies, so the policies are never copied into the plugin, where they would go stale beside the installed ones. The same package always writes the same bytes: files in name order, JSON with sorted keys, files mode 0644 (the runner 0755) and folders 0755.

### 1.1 The Other Targets

Each of these also writes `agentcad-export.json` (the package's name, the target and the version), which is how a later export knows the folder is its own.

- **`maceff`**: `policies/`, holding every policy the package ships, byte for byte, and a `README.md` beside it. `policies/` is the folder MacEff mounts as a policy root (`MACEFF_POLICY_ROOTS=agentcad=DIR/policies`); the note stays outside it so the root holds nothing but policies. The export is a copy and goes stale; the command also prints the installed package's own policy folder, which can be mounted where MacEff runs under the same Python and never goes stale.
- **`agents-md`**: one `AGENTS.md` naming every skill with its moment, every command with its one-line help, and for every policy its commands and its navigation guide: the questions, not the answers. The answers stay in the command (`agentcad policy read NAME --section N`), so the file cannot contradict the install it points at.
- **`api-tools`**: `tools.json`, one tool definition per leaf command (`name`, `description`, `input_schema`), and a `README.md` that says how a call becomes a command line. A tool's name is the command with underscores (`agentcad_probe_rays`); each property is one argument, named as the command names it, and its description ends with the option it stands for or `(positional)`. A boolean set true adds its option; a list repeats the option per item where the option repeats; positionals come last, after `--`, since an option taking several values would otherwise read them as its own. `agentcad.bundle.argv_for` does this and refuses a name the command lacks or a required one left out. The definitions say what a command takes; when to use it is in the policies.

## 2 Exporting

`agentcad plugin export --target claude-code -o DIR` writes the plugin into `DIR` (`-o` and `--output` are the same flag); `--target` is required: `claude-code`, `maceff`, `agents-md` or `api-tools`. `--marketplace` adds the marketplace manifest and belongs to `claude-code` only; with another target it is refused. The command prints the files written and how to check or use them.

`DIR` may be missing, empty, or an earlier export for the same target: an earlier export (only the entries that target writes, its `plugin.json` or its `agentcad-export.json` naming `agentcad` and the target) is removed and written again, so a stale skill never survives a re-export. Everything inside those entries belongs to the export, so a file added there by hand is removed with the rest (section 5). Anything else at the top of `DIR` is refused by name, as is a folder whose files look like an export but whose manifest names another plugin or another target, so an export never deletes a file beside its own. A refusal is one `Error:` line on stderr, exit status 2, and nothing is removed or written; a failure while writing (a full disk) can leave a partial export, which the next export replaces. A `DIR` that already existed keeps its own mode.

## 3 Checking and Using It

`claude plugin validate --strict DIR/.claude-plugin/plugin.json` checks the manifest, the skills and the agent; with a marketplace, validate `DIR/.claude-plugin/marketplace.json` as well, since validating the folder reads the marketplace manifest first. `claude --plugin-dir DIR` loads it for one session; a headless session (`claude -p --plugin-dir DIR --output-format stream-json --verbose`) lists it in its first event, with its skills, when it loaded. Add `--strict-mcp-config` to such a check when the session it is started from runs servers of its own: without it the check starts those servers too, and a server that allows one client at a time can drop the first session's connection.

The hooks show in such a session's events: a `hook_response` for SessionStart, and a refused edit comes back to the model as the tool's error with the library's practice in it. A check started from inside another harness session also loads that session's own user-level hooks, which then act on the check; `--setting-sources project,local` leaves them out.

A `maceff` export is checked by mounting it: with the variable set, `macf_tools policy list` shows the `agentcad-` policies under their root and `macf_tools policy navigate agentcad:NAME` reads one. An `api-tools` export is checked by passing a tool's input through `agentcad.bundle.argv_for` and running the result.

An export is only as current as the `agentcad` command where it runs: install agentcad there, at the version the plugin's manifest names, and re-export after upgrading.

## 4 The Hooks

The harness calls `hooks/run.sh EVENT` with its JSON payload on stdin; the runner runs `agentcad plugin hook EVENT --plugin-version V`, where `V` is the version the plugin was exported from. `agentcad plugin hook EVENT` reads the payload and prints its answer as JSON, or prints nothing when it has nothing to say; `EVENT` is `session-start`, `post-tool-use` or `pre-tool-use`. A payload that is not JSON is said on stderr with exit status 1, which a harness reports without blocking the session.

- **session-start**: silent when the installed agentcad is the plugin's version. Otherwise the session is told both versions and the two ways to make them agree: install that version, or export the plugin again.
- **post-tool-use**, on shell calls: after a call that ran `agentcad session iterate PROJECT ...`, the session is given the last iteration of that project from its record: the tray's warnings, the findings that are not `ok` (a tray warning is listed once), and the renders to read before the next iterate. Eight lines at most, then the count left and the command that shows the rest. Any other shell call, and a project whose record cannot be found, gets nothing.
- **pre-tool-use**, on the harness's edit tools (Edit, Write, MultiEdit, NotebookEdit): an edit of a file a library guards is denied, and the reason carries the library's own practice.

A library declares its guard in the `agentcad.toml` at its root:

```toml
[library]
guarded = ["parts/*/source/*", "CATALOG.md"]
practice = "Copy the part to a new revision folder and edit the copy."
```

`guarded` is one pattern or a list, matched against the file's path relative to that `agentcad.toml`, case-sensitively; `*` matches any run of characters, folder separators included. The nearest `agentcad.toml` above the file that has a `[library]` table decides; one that does not parse is skipped, and the hook says so on stderr, since a guard that file held is then not applied. `practice` is the sentence a refused session reads; without it the reason says to follow the library's own notes.

The guard sees the edits the harness makes through those tools. It does not see what a program writes: a shell command, or an agentcad command, that writes into a guarded folder is not refused. It is a reminder at the moment of the edit, not an access control.

Where no `agentcad` command is on PATH the runner says so once, at session start, and stays silent for the other events, so a missing install does not fail every tool call.

## 5 Integration with Other Policies

- `agentcad-policies`: how the skills find and read the policies they name.
- `agentcad-design-review`: the review the exported reviewer agent carries out.
- `agentcad-session`: the record the post-tool-use hook reads, and the render gate it repeats.
- `agentcad-session`, `agentcad-render-export`, `agentcad-fit` and `agentcad-print-intent`: the workflows the skills walk.

## 6 Anti-Patterns

- **Editing an export**: an edit is lost at the next export and differs from what the package ships; change the skill in agentcad.
- **A plugin without the command**: the skills name `agentcad` commands; without the install they fail at their first step.
- **Copying policies into the plugin**: a copy stops changing when agentcad does. The `maceff` copy has the same weakness, said in its own note; mount the installed folder where that is possible.
- **Treating a tool definition as guidance**: a schema says what a command accepts, not when it is the right command; a model given the tools without the policies will call them plausibly and wrongly.
- **Reading the guard as protection**: it refuses an edit tool, not a program; a library that must not change needs file permissions or review.

## 7 Evolution and Feedback

This policy ships with agentcad and changes with the plugin command and its targets; a change to either updates this policy in the same pull request.
