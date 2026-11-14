"""0010 temp/ triage — nova campaign migration (idempotent, replayable).

User rulings (2026-11-14):
- nova migrations get the dedicated track id ``nova``;
- moneta S-series stays in temp (no direction attribution, no migration);
- both program correctness AND content correctness are required.

Rules (docs/decisions/0010-temp-triage.md):
- promote  : ``lyra validate`` passes  -> directions/<family>/nova/v<NN>.yaml
- archive  : validate fails (rsi_14 ghost refs) -> stays in temp, verdict only
- duplicate: byte-identical to the direction baseline -> stays in temp
- keep-in-temp: all moneta entries (index verdict only, zero files generated)

The migration is a **copy with a provenance comment block** prepended; the
rest of the YAML is byte-identical (audit by diff). Source files in temp/
are never modified.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEMP = REPO / "strategies" / "temp" / "nova_campaign"
DIRS = REPO / "strategies" / "directions"
TRACK_ID = "nova"  # user ruling: dedicated track id for all nova migrations

_PROVENANCE_TMPL = (
    "# 0010 triage provenance (added 2026-11-14; body below is byte-identical\n"
    "# to the temp/ source. Comments only — no machine-readable field changed.)\n"
    "#   source_id:            {sid}\n"
    "#   source_repo:          ttrrei/nova\n"
    "#   source_path:          {spath}\n"
    "#   content_sha256_12:    {sha}\n"
    "#   hypothesis:           {hyp}\n"
    "#   pass_instruments:     {pass_n} of {total} (nova-side study; O18 addendum —\n"
    "#                         lyra conclusions require re-running on lyra bars)\n"
    "#   triage_verdict:       {verdict}\n"
)


def branch_name(source_id: str) -> str:
    """Derive a legal branch name from the last two number runs of the id.

    ``campaign_failed_breakout_p1_r06`` -> ``v106``; ``pullback_phase1_r18``
    -> ``v118``; ``range_p1_r09`` -> ``v109`` (100*phase + round).

    The numeric form is required: ``_VNN_RE``/``_BRANCH_RE`` demand a digit
    directly after ``v`` (``vp1_r06`` classifies UNCLASSIFIED, failing I17
    push). Per-family collision-freedom is verified at replay; the original
    id stays fully traceable via the provenance comment block + temp index.
    """
    runs = [int(n) for n in re.findall(r"\d+", source_id)]
    if len(runs) < 2:
        raise SystemExit(f"cannot derive branch from id {source_id!r} (need >=2 number runs)")
    a, b = runs[-2], runs[-1]
    if a >= 100 or b >= 100:
        raise SystemExit(f"id {source_id!r}: number runs out of the 100*a+b range")
    return f"v{100 * a + b}"


def validate(yaml_path: Path) -> tuple[bool, str]:
    r = subprocess.run(
        [str(REPO / ".venv" / "bin" / "lyra"), "validate", str(yaml_path)],
        capture_output=True, text=True, cwd=REPO,
    )
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def main() -> None:
    dry = "--dry-run" in sys.argv
    migrated, archived, dups, errors = [], [], [], []

    for meta_p in sorted(TEMP.glob("*/*/meta.json")):
        exp_dir = meta_p.parent
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        sid, fam, src = meta["id"], meta["family"], meta["source_path"]
        strat = exp_dir / "strategy.yaml"

        # duplicate detection: byte-identical to the formal direction baseline
        baseline = DIRS / fam / "v01.yaml"
        if baseline.exists() and baseline.read_bytes() == strat.read_bytes():
            dups.append((sid, fam))
            continue

        ok, msg = validate(strat)
        branch = branch_name(sid)
        target = DIRS / fam / TRACK_ID / f"{branch}.yaml"

        if not ok:
            archived.append((sid, fam, branch, msg.splitlines()[-1] if msg else ""))
            continue

        if target.exists():
            # idempotent replay: strip every comment/blank line from both and
            # compare the machine-readable lines — the provenance block is
            # comments-only, so equality on non-comment lines is exact.
            def _content_lines(p: Path) -> list[str]:
                return [ln.rstrip() for ln in
                        p.read_text(encoding="utf-8").splitlines()
                        if ln.strip() and not ln.lstrip().startswith("#")]
            if _content_lines(strat) != _content_lines(target):
                raise SystemExit(f"target exists but content differs: {target}")
            migrated.append((sid, fam, branch, "exists"))
            continue

        if not dry:
            target.parent.mkdir(parents=True, exist_ok=True)
            hyp = " ".join(meta.get("hypothesis", "").split())[:200]
            prov = _PROVENANCE_TMPL.format(
                sid=sid, spath=src, sha=meta.get("content_sha256_12", ""),
                hyp=hyp, pass_n=meta.get("pass_instruments", ""),
                total=meta.get("total_instruments", ""), verdict="promote (0010)",
            )
            target.write_text(prov + "\n" + strat.read_text(encoding="utf-8"),
                              encoding="utf-8")
        migrated.append((sid, fam, branch, "dry-run" if dry else "migrated"))

    print(f"== 0010 triage ({'DRY-RUN' if dry else 'migrate'}) ==")
    print(f"promote:   {len(migrated)}")
    for sid, fam, br, st in migrated[:10]:
        print(f"  {fam:22s} {br:10s} ({st}) {sid}")
    if len(migrated) > 10:
        print(f"  ... +{len(migrated) - 10} more")
    print(f"archive:   {len(archived)} (rsi_14 ghost refs — stay in temp)")
    for sid, fam, br, why in archived[:6]:
        print(f"  {fam:22s} {br:10s} {sid}: {why[:90]}")
    if len(archived) > 6:
        print(f"  ... +{len(archived) - 6} more")
    print(f"duplicate: {len(dups)}")
    for sid, fam in dups:
        print(f"  {fam:22s} {sid} (= directions/{fam}/v01.yaml byte-identical)")
    print(f"errors:    {len(errors)}")

    if not dry:
        # branch-name uniqueness per direction (fail fast, never silent)
        seen: dict[tuple[str, str], str] = {}
        for sid, fam, br, _ in migrated:
            key = (fam, br)
            if key in seen and seen[key] != sid:
                raise SystemExit(f"branch collision {fam}/{br}: {seen[key]} vs {sid}")
            seen[key] = sid
        print("branch uniqueness: OK (no collisions per direction)")


if __name__ == "__main__":
    main()
