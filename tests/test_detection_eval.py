"""The detection evaluation, run every time (docs/detection-audit.md).

Every scenario once, rotating through eye types and frame rates. A change
that misses a drowsy case or makes a not-drowsy case alarm fails here. The
full table (every eye type, both frame rates) is
``python tools/evaluate_detection.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bamnun import scenarios  # noqa: E402
from bamnun.evaluation import evaluate, summarise  # noqa: E402
from bamnun.session import load_config  # noqa: E402

EYES = ("medium", "small", "large", "glasses")
FPS = (30.0, 15.0)


@pytest.fixture(scope="module")
def rows():
    cases = [scenarios.build(name, EYES[i % 4], seed=11, fps=FPS[i % 2],
                             body_s=300.0 if name == "progressive" else 120.0)
             for i, name in enumerate(scenarios.all_names())]
    return {r["case"]: r for r in summarise(evaluate(cases, load_config()))}


@pytest.mark.parametrize("case", list(scenarios.DROWSY))
def test_every_drowsy_case_is_caught(rows, case):
    r = rows[case]
    assert r["detection"] == 1.0, f"{case} missed: {r}"


def test_a_microsleep_reaches_the_top_step_within_a_second_and_a_half(rows):
    assert rows["microsleep"]["reaction_s"] <= 1.5


def test_nods_are_caught_quickly(rows):
    assert rows["head_nods"]["reaction_s"] <= 15.0


@pytest.mark.parametrize("case", list(scenarios.NOT_DROWSY))
def test_no_false_alarms(rows, case):
    r = rows[case]
    assert r["false_alarms_h"] == 0.0, f"{case} alarmed: {r}"
    assert r["p90_score"] < 20.0, f"{case} scores too high: {r}"


def test_an_alert_driver_sits_near_zero(rows):
    assert rows["alert"]["rest_score"] <= 10.0
