# Plugin Export: agentcad's Skills and Reviewer in an Agent Harness

**Type**: Capability Policy (distribution)
**Scope**: Any agent or person making agentcad's skills and reviewer agent available in an agent harness
**Status**: ACTIVE
**Commands**: agentcad plugin export

## Purpose

agentcad ships its know-how in the package: policies read through `agentcad policy`, skills that walk a workflow, and a reviewer agent. A harness finds skills and agents only where it looks for them. `agentcad plugin export` lays the shipped skills and the reviewer out as a plugin that a harness loads, so a session with no memory of agentcad can run its workflows. This policy says what the export holds, what it leaves to the installed command, and how to check it.

## CEP Navigation Guide

**1 What an Export Holds**
- Which files does an export write, and where do they come from?
- What does an export never hold?

**2 Exporting**
- Which targets are there, and what does each flag do?
- What happens to the folder written into?
- When is an export refused?

**3 Checking and Using It**
- How is an export checked before it is used?
- What must be true where the plugin is used?

**4 Integration with Other Policies**
- Which policies do the exported skills read?

**5 Anti-Patterns**
- Which uses of an export defeat it?

**6 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 What an Export Holds

For the `claude-code` target an export writes:

- `.claude-plugin/plugin.json`: the plugin's name (`agentcad`), its version (the package's own), and the description, author and license from the package's metadata;
- `skills/<name>/SKILL.md` for each skill the package ships, invoked in the harness as `/agentcad:<name>`;
- `agents/design-reviewer.md`, the reviewer agent, named `agentcad:design-reviewer` there;
- `hooks/hooks.json`, with no hooks;
- with `--marketplace`, `.claude-plugin/marketplace.json`: a local marketplace offering the plugin from the same folder.

An export holds no code, no command, no permission rule and no server. The skills call the `agentcad` command and read its policies, so the policies are never copied into the plugin, where they would go stale beside the installed ones. The same package always writes the same bytes: files in name order, JSON with sorted keys, files mode 0644 and folders 0755.

## 2 Exporting

`agentcad plugin export --target claude-code -o DIR` writes the plugin into `DIR` (`-o` and `--output` are the same flag); `--target` is required and `claude-code` is the only target. `--marketplace` adds the marketplace manifest. It prints the files written and the commands that check and load the plugin.

`DIR` may be missing, empty, or an earlier export: an earlier export (only the four entries above, its `plugin.json` naming `agentcad`) is removed and written again, so a stale skill never survives a re-export. Everything inside those four entries belongs to the export, so a file added there by hand is removed with the rest (section 5). Anything else at the top of `DIR` is refused by name, as is a folder whose files look like an export but whose manifest names another plugin, so an export never deletes a file beside its own. A refusal is one `Error:` line on stderr, exit status 2, and nothing is removed or written; a failure while writing (a full disk) can leave a partial export, which the next export replaces. A `DIR` that already existed keeps its own mode.

## 3 Checking and Using It

`claude plugin validate --strict DIR/.claude-plugin/plugin.json` checks the manifest, the skills and the agent; with a marketplace, validate `DIR/.claude-plugin/marketplace.json` as well, since validating the folder reads the marketplace manifest first. `claude --plugin-dir DIR` loads it for one session; a headless session (`claude -p --plugin-dir DIR --output-format stream-json --verbose`) lists it in its first event, with its skills, when it loaded. Add `--strict-mcp-config` to such a check when the session it is started from runs servers of its own: without it the check starts those servers too, and a server that allows one client at a time can drop the first session's connection.

The plugin is only as current as the `agentcad` command where it runs: install agentcad there, at the version the plugin's manifest names, and re-export after upgrading.

## 4 Integration with Other Policies

- `agentcad-policies`: how the skills find and read the policies they name.
- `agentcad-design-review`: the review the exported reviewer agent carries out.
- `agentcad-session`, `agentcad-render-export`, `agentcad-fit` and `agentcad-print-intent`: the workflows the skills walk.

## 5 Anti-Patterns

- **Editing an export**: an edit is lost at the next export and differs from what the package ships; change the skill in agentcad.
- **A plugin without the command**: the skills name `agentcad` commands; without the install they fail at their first step.
- **Copying policies into the plugin**: a copy stops changing when agentcad does.

## 6 Evolution and Feedback

This policy ships with agentcad and changes with the plugin command and its targets; a change to either updates this policy in the same pull request.
