# Fixture Policy: Parsing Edge Cases

**Type**: Test Fixture
**Scope**: The policy reader's tests
**Status**: ACTIVE
**Commands**:

## Purpose

Exercises the format's parsing rules: fenced code hides headings, a section prefix does not match a longer number, unnumbered headings stay inside their section, and a trailing dot is ignored.

## CEP Navigation Guide

**1 First Topic**
- What does the first section hold?

**1.1 A Subtopic**
- Does 1.1 stop before 1.10?

**1.10 A Later Subtopic**
- Is 1.10 its own section?

**2 Second Topic**
- Are headings inside fences ignored?

**3 Third Topic**
- Is a trailing dot ignored?

=== CEP_NAV_BOUNDARY ===

## 1 First Topic

Text of section one.

### 1.1 A Subtopic

Text of 1.1.

#### Example

An unnumbered heading inside 1.1 stays in 1.1.

### 1.10 A Later Subtopic

Text of 1.10, which section 1.1 must not include.

## 2 Second Topic

```
## 9 Not A Heading
# also not a heading
```

~~~
### 2.5 Hidden In A Tilde Fence
~~~

Text after the fences.

### 2.1 A Real Subsection

Text of 2.1.

## 3. Third Topic

Text of section three, whose heading carries a trailing dot.

## 20 Twenty

Section twenty must not match a request for section 2.
