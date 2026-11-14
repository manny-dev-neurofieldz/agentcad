# Policies: How agentcad Explains Itself

**Type**: Capability Policy (meta)
**Scope**: Any agent or person using agentcad, and anyone adding a command to it
**Status**: ACTIVE
**Commands**: agentcad policy list, agentcad policy navigate, agentcad policy read

## Purpose

Every agentcad capability ships with a policy: a document, versioned with the code, that says what the capability is for, how to use it well, and how it fails. An agent reads the policy through the CLI before acting, so the guidance is always the guidance of the installed version and never a stale copy in a prompt. This policy says how to find and read policies, how they are written, and the contract that keeps every command covered.

## Reaching for It

- Arriving with a goal and no map: `agentcad policy navigate start`, the tool by goal (`agentcad-start`).
- Before using a command: `agentcad policy list` names the policy that governs it; navigate it, then read only the sections whose questions are yours.
- Before writing or changing a command, a flag or a policy: section 2 says what a policy holds, section 2.2 the enabling pattern every policy follows, section 3 the tests that hold them to it.

## CEP Navigation Guide

**1 Finding and Reading**
- How are the installed policies listed?
- How is a policy read without reading all of it?

**2 The Format**
- What does a policy file contain, and in what order?
- How are sections numbered?

**2.1 Parsing Rules**
- How is the navigation guide separated from the content?
- How is a section and its subsections found?

**2.2 The Enabling Pattern**
- What does every policy say beyond what its commands do?
- How is a recipe written so that it runs?
- How is a real constraint stated, so it can be checked instead of obeyed blind?
- How is a flow drawn?

**3 The Contract**
- Which commands must a policy cover, and which of their flags must it name?
- What checks hold every policy to the format and the pattern?

**4 Recipes**
- How is a policy found, navigated and read, as commands?

**5 Constraints to Probe**
- What should a policy author check before a change is done?

**6 Integration with Other Policies**
- Where else can these files be read?
- How should a skill or a document refer to a policy?

**7 Anti-Patterns**
- Which ways of writing or citing policies fail?

**8 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 Finding and Reading

`agentcad policy list` prints every installed policy with the commands it governs (`--json` for a record). `agentcad policy navigate NAME` prints the policy's navigation guide: its numbered topics, each with the questions its section answers. `agentcad policy read NAME --section N` prints that section with its subsections; `--lines START:END` prints a line range and `--from-nav-boundary` everything after the guide. Names may be given with or without the `agentcad-` prefix.

The working order is list, navigate, read: scan the questions, then read only the sections that answer the question at hand.

## 2 The Format

A policy is a markdown file in the package's `policies` folder, named `agentcad-<topic>.md`. In order it holds:

- a title line and a header of `**Type**`, `**Scope**`, `**Status**` and `**Commands**` lines, where Commands lists the full commands the policy governs, comma-separated, or says `none` for a policy about a practice rather than a command;
- `## Purpose`;
- `## Reaching for It` (section 2.2);
- `## CEP Navigation Guide`: bold numbered topics (`**1 Topic**`, `**1.1 Subtopic**`), each followed by the questions its section answers;
- the boundary line `=== CEP_NAV_BOUNDARY ===`;
- content sections numbered exactly like the guide (`## 1 Topic`, `### 1.1 Subtopic`), ending with `Recipes`, `Constraints to Probe`, then integration, anti-pattern and evolution sections.

### 2.1 Parsing Rules

The rules are fixed so that every reader of this format extracts the same text. The navigation guide is everything before the first boundary marker; a file without one shows its first 100 lines. A section is found by the first word of a heading, with a trailing dot ignored: section `2` matches headings numbered `2` and `2.x`, but not `20`, and reading stops at the next heading of the same or a higher level that does not match. Lines starting with three backticks or three tildes open and close code fences, and headings inside a fence are not headings.

### 2.2 The Enabling Pattern

A policy is written to get an agent to a result, not only to describe a command. Beside what a command does, every policy says three more things, each in a fixed place so an agent knows where to look:

- **Reaching for It**, unnumbered, after the Purpose and above the guide, so `agentcad policy navigate` shows it before any question: the results this capability gets you, and, by name, the command or policy that is the better choice for a neighbouring goal. A few lines or a table; an agent decides here whether it is in the right policy.
- **Recipes**, a numbered section before the integration section: two or more worked sequences (one for a practice policy), each the commands as typed, the lines of output that matter, and the next step in a sentence after the block. A recipe shows a route through the capability that prose would take a page to describe.
- **Constraints to Probe**, the next numbered section: the real limits of the task, each beside the command or test that tells you where you stand. A constraint stated without its probe stops an agent and explains nothing; with it, the agent can check instead of guess.

Anti-patterns stay, after the integration section, as the last word on what goes wrong.

A recipe is a fenced block with the info string `console` whose first line is `# recipe: WORKSPACE`, where the workspace is `examples` (a scratch copy of the repository's examples, the working folder above them) or `empty`. A line starting `$ agentcad` is a step; the lines under it, up to the next step, are what its output must show, each matching one line of the output, in order, with `...` standing for any text. `# exit N` says the status the step must end with (0 when not said); other `#` lines are commentary, so a line of output that starts with `#` (a heading) is quoted without its hashes, which a fragment match allows. A step's output is its stdout followed by its stderr, so a refusal's message is expected after any line it printed. A recipe under any other fence, an expected line of only `...`, and an `# exit` without a number are refused, since each would let a recipe pass while testing nothing. Steps run with a user config folder of their own, so a recipe never depends on the machine's printers or targets. The tests run every recipe in every policy (`tests/test_recipes.py`), so a recipe is a claim the build checks: quote the fragments that stay the same from run to run (counts, names, refusals), not timings or absolute paths.

```console
# recipe: empty
$ agentcad policy read start --section 1.3
1.3 Check a Fit
```

A flow (a loop, a route, a decision) is drawn as a fenced `mermaid` block, a `flowchart`, `sequenceDiagram` or `stateDiagram-v2`, which a code host renders and a terminal shows as readable text. ASCII drawings are not used.

## 3 The Contract

Every leaf command of the CLI is governed by exactly one policy, through its `**Commands**` line, and a test walks the command tree to hold that true. A policy also names every flag of the commands it governs: another test reads each command's options and looks for each one's long form, as a whole flag, in the policy's text. A pull request that adds a command or a flag adds its policy text in the same change. Policies that describe a practice rather than a command govern none.

The same tests lint every policy: plain ASCII; no absolute file paths; no names of particular people, agents or labs; code fences at the start of a line and balanced; the header fields present; and the navigation guide's numbers equal to the content's. They also hold the pattern of section 2.2: the Reaching for It heading in its place, Recipes followed by Constraints to Probe before the integration section, the number of recipes, a command or test named by every constraint, and every `mermaid` block a diagram kind a code host renders. A policy not yet written in the pattern is named in the tests' list of policies to upgrade; that list only shrinks, and a policy upgraded while still on it fails.

## 4 Recipes

Find the policy for a command, see its questions, read one answer.

```console
# recipe: empty
$ agentcad policy list
agentcad-start
governs: info
$ agentcad policy navigate engines
Reaching for It
**9 Recipes**
$ agentcad policy read engines --section 10
10 Constraints to Probe
```

`policy list` prints the map by goal first, then every policy with the commands it governs; `navigate` shows when to reach for the capability and the questions each section answers; `read --section` prints one answer with its subsections. Next: run the recipe of the section you read.

A name that is not a policy is refused with the way to find one, and a section that is not there by its number:

```console
# recipe: empty
$ agentcad policy read nosuch
# exit 1
no policy named 'nosuch' (agentcad policy list shows them)
$ agentcad policy read engines --section 99
# exit 1
section 99 not found
```

## 5 Constraints to Probe

- Every leaf command must be governed by exactly one policy, and every flag named in it: `tests/test_policy.py` walks the command tree and fails naming each unclaimed command and unnamed flag.
- A recipe must still run on the installed version: `tests/test_recipes.py` runs every recipe and names the step and the line it did not show; run the one policy's recipes with `-k NAME`.
- A section number cited from outside breaks when a section is inserted: `tests/test_policy.py` checks every citation in `docs/policy_ledger.md` against the policies; `agentcad policy navigate NAME` shows the numbers as they are.
- An installed policy may differ from the repository's: `agentcad policy list` reads the installed package, so reinstall before trusting it for an edited policy.

## 6 Integration with Other Policies

- The files follow a policy format other readers share, so an agent framework that mounts them can read them unchanged.
- A skill or document should cite a policy by name and by the question it answers, not by section number: numbers change as a policy grows, questions do not.

## 7 Anti-Patterns

- **Embedding the answer**: a skill that copies a policy's guidance goes stale when the policy changes; it should ask the question and read the answer.
- **Citing by number from outside**: "section 3.2" breaks on the next insertion.
- **A command without a policy, or a flag the policy never names**: the tests refuse both; write the policy text with the code.
- **A rule without its probe**: "never do X" with no command that shows whether X is happening makes the reader invent a reason, and the invented one is usually wrong; state the limit beside its probe (section 2.2).
- **A recipe that tests nothing**: quoting a timing or an absolute path makes it fail on the next machine; quoting nothing makes it pass on a broken one. The tests refuse a recipe that expects no output.

## 8 Evolution and Feedback

This policy changes with the policy commands and the format; a change to either updates this policy in the same pull request.
