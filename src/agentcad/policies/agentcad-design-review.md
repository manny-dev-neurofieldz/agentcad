# Design Review: A Peer's Rubric

**Type**: Practice Policy (review)
**Scope**: Any agent or person reviewing a design made with agentcad, and any author preparing one for review
**Status**: ACTIVE
**Commands**: none

## Purpose

An author cannot measure what the author did not think to ask. A review is an instrument pointed at those blind spots: a peer who builds and probes the design independently, scores it on a fixed rubric with evidence, and asks for the one change that matters most. Its value is in the findings the author could not have made; a review that confirms the render has measured nothing. This policy says what an author hands over, the order a reviewer works in, the rubric, and what a review produces.

## CEP Navigation Guide

**1 The Packet**
- What does an author hand a reviewer?
- Why is the design frozen first?

**2 The Order of Work**
- What does a reviewer do before reading the author's conclusions?
- Which probes find what a render hides?

**3 The Rubric**
- On what is a design scored, and with what evidence?

**4 Findings and the One Revision**
- How are findings ranked and grouped?
- What is the one revision, and how is it chosen?

**5 What a Review Produces**
- What does the record of a review hold, and what does a reviewer not do?

**6 Integration with Other Policies**
- Which policies give a reviewer its instruments?

**7 Anti-Patterns**
- Which reviews measure nothing?

**8 Evolution and Feedback**
- How does this policy change?

=== CEP_NAV_BOUNDARY ===

## 1 The Packet

The author hands over the program, the renders, the spec, the measurements, the author's own critique and, for a replication or a revision, the original. Freeze the design first: tag the session (`agentcad session tag`) and give the reviewer the tag, so the reviewer scores a fixed revision while work continues. A design rewritten during a review gets a review of a superseded version. Give the packet's current images; overlays reused from an earlier revision make the reviewer diff programs to trust them.

## 2 The Order of Work

Build the program and probe the result before reading anything the author concluded. Section the part at mid-thickness against the original; cast rays for widths and wall thicknesses; scan along each cavity's axis for throats, seats and caps; list the edges under a quarter of a millimetre for skins and slivers; perturb the parameters (`agentcad probe knobs`) to find knobs that move nothing and values that break the part silently. Then read the author's spec against the author's build, re-run the author's own instruments against the author's claims, and read the author's critique last, so the reviewer's list is the reviewer's own.

Hunt the silent-valid part: a solid that reports valid while a feature never built, a vent stops short of its wall or two bodies only touch. Validity is the claim to test, not the reassurance.

## 3 The Rubric

Score four things, each with evidence: a program line or a measured number ("8.2 against 6.0 at x -4", not "looks fuller").

- **Function**: does the part do its job? Is the direction of every mate stated and right, and does each feature serve the job the spec gives it?
- **Constructive-technique choice**: are the operations the right ones for the shape (a profile revolved with its features in it, a round made as a prism and not a propagating fillet, curves recovered rather than traced)?
- **Parametrization sanity**: are the knobs the quantities a user turns, are derived values derived, does any knob move nothing, is any number written twice?
- **Printability**: is the orientation argued, are walls and features above the process's minimums, where do supports land, what does the material do?

## 4 Findings and the One Revision

List up to five findings, ranked by consequence. For a replication or a revision, sort them into three bins: where the design is better than the reference, where it is worse, and the weaknesses both share. Never recommend copying the reference; recommend what is right.

Name one revision: the single construction change that retires the most findings. Build it and measure it before recommending it, so the recommendation carries its own evidence. Then say what the author's critique missed: it is how the author learns where to look next time.

## 5 What a Review Produces

A review's record holds the rubric scores with their evidence, the ranked findings, the one revision with its measurements, and what the critique missed, so the author can act on every line. A reviewer changes nothing in the design, the project or its records; the author applies the revision, and the next iteration shows whether it retired the findings.

## 6 Integration with Other Policies

- `agentcad-session`: tags, the frozen copies a review scores.
- `agentcad-compare`, `agentcad-probe-inspect`, `agentcad-probe-recover`, `agentcad-probe-construction`: the reviewer's instruments.
- `agentcad-design-practice` and `agentcad-build123d`: the practices the rubric scores against.
- `agentcad-fit`: the evidence for a mate.
- `agentcad-policies`: how this policy is found and read.

## 7 Anti-Patterns

- **Reviewing the render**: four views confirm a silhouette; they say nothing about walls, sizes or connectivity.
- **Reading the author first**: the review becomes the author's list in a second voice.
- **A finding without a number**: an impression the author cannot act on.
- **Many revisions**: a list of changes is not a decision; name the one.
- **A moving target**: a design rewritten while it is reviewed.

## 8 Evolution and Feedback

This policy changes as reviews teach; a recurring finding is added to the rubric's wording when it has appeared in more than one review.
