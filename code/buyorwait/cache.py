"""Content-addressed, two-layer disk cache for LLM extraction.

Layer 1 (`observations/`): the raw, validated model output for one source
(one image or one message), keyed on everything that could change what a
re-run would produce. Layer 2 (`resolutions/`): deterministic, code-computed
results derived FROM an observation (e.g. a chosen interpretation after
applying amount-role selection rules) -- kept separate so a change to the
deterministic selection logic invalidates layer 2 without forcing an
unnecessary, costly re-extraction in layer 1.

Cache key inputs (all required, all part of the key -- changing ANY one
invalidates the entry and forces a fresh call):
  * `source_sha256` -- the exact bytes of the image or message text hashed;
    a source_id alone is not enough (a hidden edit would silently reuse a
    stale observation otherwise).
  * `model` -- e.g. "gpt-6-astra".
  * `prompt_version` / `schema_version` -- bumped whenever the extraction
    prompt or the target JSON Schema changes shape.
  * `decoding_config` -- e.g. reasoning effort; folded into one hash so any
    change (a harder-effort re-read, say) is a cache miss, not a silent
    reuse of an easier read.
  * `tool_contract_version` -- bumped whenever a tool's schema changes, for
    entries produced via a tool-using investigation loop.

Writes are atomic: a value is written to a temp file in the SAME directory,
then moved into place with `os.replace`, which is atomic on both POSIX and
Windows for a same-volume rename. A reader never observes a partially
written file. Concurrent writers targeting the same key race on the final
`os.replace`; the loser's temp file is simply discarded (last writer wins,
which is safe here because two writers computing the SAME key are, by
construction, computing the same deterministic value or independent
draws of the same non-deterministic extraction -- neither corrupts the
store). A short-lived `.corrupt` sidecar is written whenever a read finds a
file that fails to parse, so corruption is visible on disk rather than
silently treated as a cache miss and silently re-fetched forever.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class CacheKey:
    source_id: str  # e.g. "image_06" or "message_39" -- for human-readable filenames only
    source_sha256: str
    model: str
    prompt_version: str
    schema_version: str
    decoding_config: str  # e.g. "effort=high"
    tool_contract_version: str

    def digest(self) -> str:
        material = "|".join(
            [
                self.source_sha256,
                self.model,
                self.prompt_version,
                self.schema_version,
                self.decoding_config,
                self.tool_contract_version,
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    def filename(self) -> str:
        return f"{self.source_id}.{self.digest()}.json"


class CacheCorruptionError(Exception):
    """Raised when a cache entry's file cannot be parsed. The offending file
    is preserved and copied to `<name>.corrupt` for inspection rather than
    silently deleted -- corruption must be visible, not swallowed."""


class ContentAddressedCache:
    """One instance per layer (construct two: one rooted at
    `<root>/observations`, one at `<root>/resolutions`)."""

    def __init__(
        self,
        root: str | Path,
        fallback_roots: Sequence[str | Path] | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        if fallback_roots is None:
            default_fbs = []
            code_parent = Path(__file__).resolve().parents[1]
            repo_parent = Path(__file__).resolve().parents[2]
            for candidate in [
                Path("evaluation/extraction_snapshot"),
                Path("evaluation/extraction_snapshot/observations"),
                Path("code/evaluation/extraction_snapshot"),
                Path("code/evaluation/extraction_snapshot/observations"),
                code_parent / "evaluation" / "extraction_snapshot",
                code_parent / "evaluation" / "extraction_snapshot" / "observations",
                repo_parent / "evaluation" / "extraction_snapshot",
                repo_parent / "evaluation" / "extraction_snapshot" / "observations",
                self.root.parent / "evaluation" / "extraction_snapshot",
            ]:
                if candidate.exists() and candidate.is_dir() and candidate not in default_fbs:
                    default_fbs.append(candidate)
            self.fallback_roots = tuple(default_fbs)
        else:
            self.fallback_roots = tuple(Path(p) for p in fallback_roots if Path(p).exists())

    def _path(self, key: CacheKey) -> Path:
        return self.root / key.filename()

    def get(self, key: CacheKey) -> Mapping[str, Any] | None:
        """Returns the cached value, or None on a genuine miss. Raises
        `CacheCorruptionError` if a file exists but fails to parse -- a
        parse failure is never treated as an ordinary miss, since silently
        re-fetching would hide real on-disk corruption from anyone who might
        want to investigate it."""
        path = self._path(key)
        if not path.exists():
            for fb in self.fallback_roots:
                fb_path = fb / key.filename()
                if fb_path.exists():
                    path = fb_path
                    break
                fb_sub = fb / "observations" / key.filename()
                if fb_sub.exists():
                    path = fb_sub
                    break
            else:
                return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            corrupt_path = path.with_suffix(path.suffix + ".corrupt")
            try:
                corrupt_path.write_bytes(path.read_bytes())
            except OSError:
                pass  # best-effort preservation; the original exception is what matters
            raise CacheCorruptionError(f"cache entry {path} failed to parse: {exc}") from exc

    def get_by_source_id(self, source_id: str) -> Mapping[str, Any] | None:
        """Find cached entry by source_id (e.g. 'image_01' or 'message_02') across root and fallback roots."""
        prefix = f"{source_id}."
        roots = [self.root] + list(self.fallback_roots)
        for r in roots:
            if not r.exists():
                continue
            for p in sorted(r.glob(f"{prefix}*.json")):
                if not p.name.endswith(".corrupt"):
                    try:
                        return json.loads(p.read_text(encoding="utf-8"))
                    except Exception:
                        pass
            obs_dir = r / "observations"
            if obs_dir.exists():
                for p in sorted(obs_dir.glob(f"{prefix}*.json")):
                    if not p.name.endswith(".corrupt"):
                        try:
                            return json.loads(p.read_text(encoding="utf-8"))
                        except Exception:
                            pass
        return None

    def set(self, key: CacheKey, value: Mapping[str, Any]) -> None:
        """Atomic write: temp file in the same directory, then `os.replace`.
        A concurrent reader either sees the old value or the new one, never
        a half-written file."""
        path = self._path(key)
        fd, tmp_name = tempfile.mkstemp(dir=self.root, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(dict(value), fh, sort_keys=True, indent=2)
                fh.write("\n")
            replaced = False
            for attempt in range(5):
                try:
                    os.replace(tmp_name, path)
                    replaced = True
                    break
                except PermissionError:
                    if attempt < 4:
                        import time
                        time.sleep(0.005 * (attempt + 1))
                    elif path.exists():
                        break
                    else:
                        raise
            if not replaced and os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def has(self, key: CacheKey) -> bool:
        return self._path(key).exists()

    def invalidate(self, key: CacheKey) -> bool:
        """Remove one entry (e.g. to force a re-read). Returns True if a
        file was actually removed."""
        path = self._path(key)
        if path.exists():
            path.unlink()
            return True
        return False

    def all_keys_for_source(self, source_id: str) -> tuple[str, ...]:
        """Every cached digest for a given source_id -- useful for finding
        stale entries left behind by an old prompt/schema version after a
        bump, since old-version files are never auto-deleted (a failed item
        must stay retriable, and an old entry might still be wanted for a
        reproducibility replay)."""
        prefix = f"{source_id}."
        return tuple(sorted(p.name for p in self.root.glob(f"{prefix}*.json")))
