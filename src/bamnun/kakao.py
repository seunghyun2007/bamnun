"""Kakao keys and the Kakao Mobility directions call (docs/SPEC.md, section 9).

Two keys, both from Kakao Developers, kept out of git in ``frontend/.env``
(or in the environment):

    KAKAO_JS_KEY=...     the map and place search in the app. Meant to be
                         public; Kakao only accepts it from the web addresses
                         registered for the app (e.g. http://localhost:8000).
    KAKAO_REST_KEY=...   driving directions. Secret, so it stays here: the
                         app asks the device (``GET /api/route``), and the
                         device asks Kakao.

Stdlib only. Runs on the server's worker threads, never the camera loop.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from .session import repo_root

DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/directions"
MAX_POINTS = 1500

# The driver's vehicle -> Kakao's car_type, which sets tolls. Kakao's car
# routing has no height or weight limits, so a truck gets a car's roads
# (SPEC.md, Q3); the app says so.
CAR_TYPE = {"long_haul": 4, "delivery": 3, "bus": 3, "taxi": 1, "car": 1}


class KakaoError(RuntimeError):
    pass


class NoKey(KakaoError):
    pass


def read_env(path: Optional[Path] = None) -> dict[str, str]:
    path = path or repo_root() / "frontend" / ".env"
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def key(name: str) -> str:
    return os.environ.get(name) or read_env().get(name, "")


def parse_point(s: str) -> tuple[float, float]:
    """"lng,lat" -> (lng, lat), inside Korea's rough bounds."""
    try:
        lng, lat = (float(x) for x in s.split(","))
    except ValueError:
        raise ValueError(f"expected lng,lat, not {s!r}") from None
    if not (120.0 <= lng <= 135.0 and 30.0 <= lat <= 45.0):
        raise ValueError(f"{s!r} is not in Korea")
    return lng, lat


def thin(points: list[list[float]], limit: int = MAX_POINTS) -> list[list[float]]:
    if len(points) <= limit:
        return points
    step = len(points) / (limit - 1)
    out = [points[int(i * step)] for i in range(limit - 1)]
    out.append(points[-1])
    return out


def summarise(data: dict[str, Any]) -> dict[str, Any]:
    """Kakao's response -> distance, time and the line to draw."""
    routes = data.get("routes") or []
    if not routes:
        raise KakaoError("Kakao returned no route")
    r = routes[0]
    if r.get("result_code", 0) != 0:
        raise KakaoError(str(r.get("result_msg") or "no route between these places"))
    s = r.get("summary") or {}
    pts: list[list[float]] = []
    for sec in r.get("sections") or []:
        for road in sec.get("roads") or []:
            v = road.get("vertexes") or []
            pts.extend([v[i], v[i + 1]] for i in range(0, len(v) - 1, 2))
    fare = s.get("fare") or {}
    return {"distance_m": int(s.get("distance", 0)), "duration_s": int(s.get("duration", 0)),
            "toll_won": int(fare.get("toll", 0) or 0), "path": thin(pts)}


def directions(origin: str, destination: str, car_type: int = 1,
               rest_key: Optional[str] = None, timeout: float = 10.0) -> dict[str, Any]:
    o, d = parse_point(origin), parse_point(destination)
    rest_key = rest_key if rest_key is not None else key("KAKAO_REST_KEY")
    if not rest_key:
        raise NoKey("no Kakao REST key: add KAKAO_REST_KEY=... to frontend/.env")
    q = urllib.parse.urlencode({"origin": f"{o[0]},{o[1]}", "destination": f"{d[0]},{d[1]}",
                                "priority": "RECOMMEND", "car_type": int(car_type),
                                "summary": "false"})
    req = urllib.request.Request(f"{DIRECTIONS_URL}?{q}",
                                 headers={"Authorization": f"KakaoAK {rest_key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:200]
        raise KakaoError(f"Kakao said {exc.code}: {body}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise KakaoError(f"can't reach Kakao ({exc}); is this device online?") from None
    return summarise(data)
