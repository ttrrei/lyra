# Decision 0011: Log governance v1 (Action Log archive and slimmer rules)

> **中文**: [0011-action-log-governance.md](./0011-action-log-governance.md)

## Meta

| Field | Value |
|---|---|
| ID | `0011` |
| Title | Log governance v1: Action Log archive and slimmer rules |
| Status | approved |
| Owner | `ttrrei` |
| Created | `2026-11-22` |
| Related proposal | none |
| Related requirements | none |
| Related HLD | none |
| Supersedes | Changes the log-related rules in `AGENTS.md`; replaces the "maintenance rules" at the top of the old `docs/ACTION_LOG.md` |

## 1. Problem

The central log can no longer be read in one pass by a person or an AI: it records the full process of every piece of work rather than "what was done", and its state block goes stale. The log must become a short, trustworthy timeline again.

## 2. Background

- Size: the old `ACTION_LOG.md` is 251 lines / about 157K chars and `ACTION_LOG.en.md` 262 lines / about 261K chars, mostly single very long lines (#132 and #133 are several thousand characters each: requirements background, every review finding, regression-test lists, E2E process). Neither weak models nor people can digest this in one read.
- Two ledgers: #1–#83 are in the dated tables (`## 2026-11-05 / 11-06`), while #84–#133 were all appended to the `## 修订记录` (revision history) table at the end (columns date / version / change / where); the version column is not monotonic — for example #133 (1.80) sits before #132 (1.79).
- Stale state: `## Current state` carries both an `Updated` and an `Updated (prev)` row (thousands of characters each, re-describing #129–#133) and still says "waiting for `git push`, `origin/main = 526f2ea`" although GitHub main has moved on.
- The current rule (`AGENTS.md`) demands "every working turn must add a row and refresh the state block", which is exactly what makes the log swell to satisfy the rule.

## 3. Plan

### 3.1 What we do

1. Freeze the old logs whole as an archive: `git mv` to `docs/ACTION_LOG.archive.md` / `docs/ACTION_LOG.archive.en.md`, adding only an archive banner and fixing the cross-links at the top; the content is untouched.
2. The new `docs/ACTION_LOG.md` / `.en.md` contain three parts only: short maintenance rules, a Current state of at most 10 rows, and one entries table from #134 (`# | Date | Kind | What | Where`).
3. Rewrite the log-related rules in `AGENTS.md` (Where we are, Documentation conventions, Non-negotiables, Working style, References):
   - log only real changes or decision / review conclusions; pure discussion or diagnosis with no change is not logged;
   - 2–4 sentences per entry, detail goes to `docs/decisions/`, `docs/review/` or the commit;
   - Current state describes the state *now*, overwritten in place, no history;
   - Zh/En must carry the same information, not word-for-word translations;
   - look up old numbers by searching the archive, never load it whole.

### 3.2 What we don't do

- No rewriting, compressing, deleting or renumbering of the old history.
- No generated index of the old ledger: it has two table formats and cannot be parsed reliably by machine.
- No code changes; no changes to other docs (their `#N` references stay valid because the numbers live in the archive).

### 3.3 Boundaries

- Once frozen, the archive is never edited; new entries are written only in the new log, numbered on from #134.
- Entries in the new log must not grow back into development reports: more than about 120 words means the detail is in the wrong place.

## 4. Invariants

- The log is append-only; an overturned entry gets a new "overturns #N" entry.
- Numbers increase monotonically without repeats (from #134, continuing the archive's #133).
- `ACTION_LOG.md` / `.en.md` and the archive `.md` / `.en.md` always exist as pairs and carry the same information.
- `## Current state` is at most 10 rows and describes the current state only.

## 5. Tests

There is no code change; the checks are:

- All four files (new log and archive, both languages) exist and their relative links resolve.
- `grep -n "#113" docs/ACTION_LOG.archive.md` finds the old entry.
- `bash scripts/alpha_gate.sh`, `python -m pyflakes lyra tests` and `python -m pytest -q` are unaffected.

## 6. Rollback

`git revert` the commit to restore the original files; the archive was produced with `git mv`, so the old log's history is not lost.

## 7. Approval

Approved (`ttrrei`, 2026-11-22).

## 8. Revision history

| Date | Version | Change |
|---|---|---|
| 2026-11-22 | 0.1 | First draft. |
