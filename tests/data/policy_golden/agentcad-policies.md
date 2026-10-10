# Policies: How agentcad Explains Itself

**Type**: Capability Policy (meta)
**Scope**: Any agent or person using agentcad, and anyone adding a command to it
**Status**: ACTIVE
**Commands**: agentcad policy list, agentcad policy navigate, agentcad policy read

## Purpose

Every agentcad capability ships with a policy: a document, versioned with the code, that says what the capability is for, how to use it well, and how it fails. An agent reads the policy through the CLI before acting, so the guidance is always the guidance of the installed version and never a stale copy in a prompt. This policy says how to find and read policies, how they are written, and the contract that keeps every command covered.

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

**3 The Contract**
- Which commands must a policy cover?
- What checks hold every policy to the format?

**4 Integration with Other Policies**
- Where else can these files be read?
- How should a skill or a document refer to a policy?

**5 Anti-Patterns**
- Which ways of writing or citing policies fail?

**6 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 Finding and Reading

`agentcad policy list` prints every installed policy with the commands it governs (`--json` for a record). `agentcad policy navigate NAME` prints the policy's navigation guide: its numbered topics, each with the questions its section answers. `agentcad policy read NAME --section N` prints that section with its subsections; `--lines START:END` prints a line range and `--from-nav-boundary` everything after the guide. Names may be given with or without the `agentcad-` prefix.

The working order is list, navigate, read: scan the questions, then read only the sections that answer the question at hand.

## 2 The Format

A policy is a markdown file in the package's `policies` folder, named `agentcad-<topic>.md`. In order it holds:

- a title line and a header of `**Type**`, `**Scope**`, `**Status**` and `**Commands**` lines, where Commands lists the full commands the policy governs, comma-separated;
- `## Purpose`;
- `## CEP Navigation Guide`: bold numbered topics (`**1 Topic**`, `**1.1 Subtopic**`), each followed by the questions its section answers;
- the boundary line `=== CEP_NAV_BOUNDARY ===`;
- content sections numbered exactly like the guide (`## 1 Topic`, `### 1.1 Subtopic`), ending with integration, anti-pattern and evolution sections.

### 2.1 Parsing Rules

The rules are fixed so that every reader of this format extracts the same text. The navigation guide is everything before the first boundary marker; a file without one shows its first 100 lines. A section is found by the first word of a heading, with a trailing dot ignored: section `2` matches headings numbered `2` and `2.x`, but not `20`, and reading stops at the next heading of the same or a higher level that does not match. Lines starting with three backticks or three tildes open and close code fences, and headings inside a fence are not headings.

## 3 The Contract

Every leaf command of the CLI is governed by exactly one policy, through its `**Commands**` line, and a test walks the command tree to hold that true. A pull request that adds a command adds or extends a policy in the same change. Policies that describe a practice rather than a command may govern none.

The same tests lint every policy: plain ASCII; no absolute file paths; no names of particular people, agents or labs; code fences at the start of a line and balanced; the header fields present; and the navigation guide's numbers equal to the content's.

## 4 Integration with Other Policies

- The files follow a policy format other readers share, so an agent framework that mounts them can read them unchanged.
- A skill or document should cite a policy by name and by the question it answers, not by section number: numbers change as a policy grows, questions do not.

## 5 Anti-Patterns

- **Embedding the answer**: a skill that copies a policy's guidance goes stale when the policy changes; it should ask the question and read the answer.
- **Citing by number from outside**: "section 3.2" breaks on the next insertion.
- **A command without a policy**: the tests refuse it; write the policy with the command.

## 6 Evolution and Feedback

This policy changes with the policy commands and the format; a change to either updates this policy in the same pull request.
