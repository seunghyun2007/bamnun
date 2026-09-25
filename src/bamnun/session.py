"""Config loading and session logging.

The session log is not an afterthought. It is the training set for the learned
model that replaces the hand-weighted fusion later, and it is the evidence
base for every number that goes on the poster. Log generously, in a format
that pandas opens without argument.
"""

from __future__ import annotations

import csv
import json
import logging
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("bamnun.session")


def repo_root() -> Path:
    """Repo root, assuming this file lives at <root>/src/bamnun/session.py."""
    return Path(__file__).resolve().parents[2]


def deep_update(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_update(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Optional[str | Path] = None,
                overrides: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    import yaml

    default = repo_root() / "config" / "default.yaml"
    with open(default, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    if path is not None:
        p = Path(path)
        if p.exists() and p.resolve() != default.resolve():
            with open(p, "r", encoding="utf-8") as fh:
                cfg = deep_update(cfg, yaml.safe_load(fh) or {})

    if overrides:
        cfg = deep_update(cfg, overrides)
    return cfg


class SessionLogger:
    """Writes one CSV of per-frame features plus one JSONL of events."""

    def __init__(self, cfg: dict[str, Any], tag: str = "") -> None:
        self.dir = repo_root() / str(cfg.get("dir", "runs"))
        self.dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{stamp}{('_' + tag) if tag else ''}"
        self.csv_path = self.dir / f"{name}_frames.csv"
        self.event_path = self.dir / f"{name}_events.jsonl"
        self.meta_path = self.dir / f"{name}_meta.json"

        self.period = 1.0 / max(float(cfg.get("csv_hz", 10.0)), 0.1)
        self._last_write = -1e9
        self._csv_fh = None
        self._writer = None
        self._event_fh = open(self.event_path, "a", encoding="utf-8") \
            if cfg.get("log_events", True) else None
        self._n_frames = 0
        self._t_start = time.monotonic()

    # ----------------------------------------------------------------- #

    def write_meta(self, meta: dict[str, Any]) -> None:
        with open(self.meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2, default=str)

    def log_frame(self, feature_frame, state) -> None:
        if feature_frame.t - self._last_write < self.period:
            return
        self._last_write = feature_frame.t

        row: dict[str, Any] = feature_frame.to_row()
        row.update({
            "score": round(state.score, 4),
            "level": state.level,
            "level_name": state.level_name,
            "kss": round(state.kss, 2),
            "distracted": int(state.distracted),
            "distraction_reason": state.distraction_reason,
            "confidence": round(state.confidence, 3),
        })
        for k, v in (state.components or {}).items():
            row[f"c_{k}"] = round(v, 4)

        if self._writer is None:
            self._csv_fh = open(self.csv_path, "w", newline="", encoding="utf-8")
            self._writer = csv.DictWriter(self._csv_fh, fieldnames=list(row.keys()))
            self._writer.writeheader()
        self._writer.writerow(row)
        self._n_frames += 1
        if self._n_frames % 50 == 0 and self._csv_fh is not None:
            self._csv_fh.flush()

    def log_event(self, kind: str, payload: Any) -> None:
        if self._event_fh is None:
            return
        if is_dataclass(payload) and not isinstance(payload, type):
            payload = asdict(payload)
        rec = {
            "wall": datetime.now().isoformat(timespec="milliseconds"),
            "mono": round(time.monotonic() - self._t_start, 3),
            "kind": kind,
            "payload": payload,
        }
        self._event_fh.write(json.dumps(rec, default=str) + "\n")
        self._event_fh.flush()

    def close(self) -> None:
        wrote_csv = self._csv_fh is not None
        for fh in (self._csv_fh, self._event_fh):
            if fh is not None:
                try:
                    fh.flush()
                    fh.close()
                except Exception:
                    pass
        # The CSV is created lazily by the first log_frame, and log_frame only
        # runs once calibration is complete. Announcing the path unconditionally
        # claimed a file that was never created, which reads as a write failure
        # rather than as "this run never got past calibration".
        if wrote_csv:
            log.info("session written: %s (%d frames)", self.csv_path, self._n_frames)
        else:
            log.info("no frames logged (calibration never completed); "
                     "events and meta written to %s", self.dir)
