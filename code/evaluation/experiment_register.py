"""The experiment register: an append-only JSONL log of every evaluation run,
recording exactly which request_ids were used and their exposure status.

This exists specifically to prevent the "repeated tuning on a tiny sample"
weakness named in evaluation/workflow.md section 1. Every entry states
plainly whether its request_ids were already seen during preparatory
research (the 25 public samples -- always `PRIOR_RESEARCH_EXPOSED`) or are
independently constructed (`INDEPENDENT_SYNTHETIC`, for the fixtures in
code/evaluation/fixtures/). A reviewer reading this file can tell at a glance
that no reported result is being passed off as independent hidden-label
evidence when it is not.

Append-only: `append_entry` opens the file in "a" mode and writes one JSON
line; it never reads-modify-writes the whole file, so a crash mid-run cannot
corrupt or lose prior entries.
"""

from __future__ import annotations

import json
from pathlib import Path

from .schemas import ExperimentEntry

PRIOR_RESEARCH_EXPOSED = "prior_research_exposed"
INDEPENDENT_SYNTHETIC = "independent_synthetic"

_VALID_EXPOSURES = (PRIOR_RESEARCH_EXPOSED, INDEPENDENT_SYNTHETIC)

# The 25 public sample request_ids. Any experiment entry covering any of
# these MUST be tagged PRIOR_RESEARCH_EXPOSED -- `append_entry` enforces this
# rather than trusting the caller to remember it.
PUBLIC_SAMPLE_REQUEST_IDS = frozenset(f"request_{i:02d}" for i in range(1, 26))


class ExperimentRegisterError(ValueError):
    pass


def append_entry(path: str | Path, entry: ExperimentEntry) -> None:
    if entry.exposure not in _VALID_EXPOSURES:
        raise ExperimentRegisterError(f"exposure must be one of {_VALID_EXPOSURES}, got {entry.exposure!r}")

    covers_public_samples = bool(set(entry.request_ids) & PUBLIC_SAMPLE_REQUEST_IDS)
    if covers_public_samples and entry.exposure != PRIOR_RESEARCH_EXPOSED:
        raise ExperimentRegisterError(
            f"entry {entry.experiment_id!r} covers one or more public sample request_ids but is "
            f"tagged {entry.exposure!r}; it must be tagged {PRIOR_RESEARCH_EXPOSED!r}"
        )

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "experiment_id": entry.experiment_id,
        "timestamp_iso": entry.timestamp_iso,
        "commit": entry.commit,
        "request_ids": list(entry.request_ids),
        "exposure": entry.exposure,
        "report_summary_path": entry.report_summary_path,
        "notes": entry.notes,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def read_entries(path: str | Path) -> tuple[ExperimentEntry, ...]:
    path = Path(path)
    if not path.exists():
        return ()
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            out.append(
                ExperimentEntry(
                    experiment_id=d["experiment_id"],
                    timestamp_iso=d["timestamp_iso"],
                    commit=d["commit"],
                    request_ids=tuple(d["request_ids"]),
                    exposure=d["exposure"],
                    report_summary_path=d.get("report_summary_path"),
                    notes=d.get("notes", ""),
                )
            )
    return tuple(out)
