# Decision Doc Template

> **中文**: [TEMPLATE.md](./TEMPLATE.md)
>
> Every Lyra feature must have a decision doc. Copy this template and
> complete it **before** writing code. Decision docs are **append-only**
> (historical decisions are not deleted; add a new revision row or a new
> decision doc that supersedes it).

## Meta

| Field | Value |
|---|---|
| ID | `NNNN` (4-digit zero-padded, incrementing from 0002) |
| Title | `<feature name>` |
| Status | proposal / approved / implemented / retired |
| Owner | `ttrrei` |
| Created | `YYYY-MM-DD` |
| Related proposal | `docs/proposals/<name>.md` (if any) |
| Related requirements | `docs/requirements.md` §R? |
| Related HLD | `docs/hld.md` §? |
| Supersedes | `NNNN` (if any) |

## 1. Problem

In 1-3 sentences answer: **what problem does this feature solve?**
(Not "what do we do", but "why do we do it".)

## 2. Background

- What is the current state? (How did moneta / nova do it, and why is
  that insufficient?)
- What are the related historical decisions? (link to older decision docs)
- What are the related open questions? (link to `docs/open-questions.md`)

## 3. Plan

### 3.1 What we do

- Concrete interfaces / CLI / file layout.
- Which files to add / modify / delete at the code level.

### 3.2 What we do NOT do

- Explicitly list what this feature does **not** do (prevents scope
  creep).
- If something "looks related" is out of scope, say why (which feature
  it is deferred to).

### 3.3 Boundaries

- Input / output contracts.
- Boundary with OCI (what is read / written / where credentials come
  from).
- Boundary with alpha (does it touch alpha files / does it affect alpha
  semantics).
- Compatibility boundary with moneta / nova (backward-compatible?
  compatible with Moneta's 332 strategies?).

## 4. Invariants

Invariants this feature must **continuously guarantee**. Reference I1-I14
from `docs/hld.md` §4 or add new invariants.

| # | Invariant | Source |
|---|---|---|
| I? | ... | new from this feature / I1 (HLD §4) |

## 5. Tests

Test scenarios that must be covered (pytest case names + one-line
description):

| Test | Scenario |
|---|---|
| `test_<feature>_<case>` | <one-line> |

## 6. Rollback

If this feature ships and breaks, **how do we roll back**?
- Code: which commit / which files to revert.
- Data: do we delete files on OCI / clear local `data/`.
- Compatibility: after rollback, can Moneta / Nova strategies still run?

## 7. Approval

- [ ] User review
- [ ] AI review (second model)
- [ ] Tests all green
- [ ] 332-strategy regression passes (if applicable)
- [ ] OCI end-to-end passes (if OCI is involved)

## 8. Revision history

| Date | Version | Change |
|---|---|---|
| YYYY-MM-DD | 0.1 | Initial draft. |
