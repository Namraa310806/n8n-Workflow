import math
from typing import Dict, Any, List
from datetime import datetime, timezone


def log1p_norm(x: float) -> float:
    return math.log1p(max(0.0, x))


def decay_multiplier(published_iso: str, half_life_days: int = 30) -> float:
    try:
        dt = datetime.fromisoformat(published_iso.replace("Z", "+00:00"))
    except Exception:
        return 1.0
    age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    return math.exp(-math.log(2) * age_days / half_life_days)


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_item_scores(item: Dict[str, Any], stats: Dict[str, Any] = None) -> Dict[str, float]:
    """Compute V, E, T normalized components for a single evidence item.

    stats is optional baseline stats for percentile mapping; for now we use simple heuristics.
    """
    metrics = item.get("metrics", {})
    # volume: views or search index
    views = metrics.get("views") or 0
    # For trends entries, use interest metric
    if item.get("platform") == "GoogleTrends":
        # use growth pct as trend and use average interest as volume proxy
        iot = metrics.get("interest_over_time", {})
        # compute avg interest
        vals = []
        for v in iot.values():
            if isinstance(v, dict):
                # handle pandas->dict shape
                vals.append(list(v.values())[0])
            else:
                vals.append(v)
        views = int(sum(vals) / max(1, len(vals)))

    V_raw = log1p_norm(views)
    # map V_raw to [0,1] using heuristic: divide by a scale constant
    V_norm = clamp01(V_raw / 10.0)

    # engagement
    likes = metrics.get("likes") or 0
    comments = metrics.get("comments") or metrics.get("replies") or 0
    like_to_view = (likes / views) if views > 0 else 0.0
    comment_to_view = (comments / views) if views > 0 else 0.0
    # combine ratios
    E_raw = 0.6 * like_to_view + 0.4 * comment_to_view
    # map E_raw (which typically is small) to [0,1] via scaling
    E_norm = clamp01(E_raw * 10.0)

    # trend
    growth = metrics.get("growth_pct_30d") or 0.0
    # apply tanh dampening
    T_raw = math.tanh(growth)
    T_norm = clamp01((T_raw + 1) / 2)

    # decay for recency if published_at present
    pub = metrics.get("published_at") or metrics.get("first_post_ts") or None
    D = 1.0
    if pub:
        try:
            D = decay_multiplier(pub)
        except Exception:
            D = 1.0

    return {"V": V_norm, "E": E_norm, "T": T_norm, "D": D}


def aggregate_workflow(evidence: List[Dict[str, Any]], weights: Dict[str, float] = None) -> Dict[str, Any]:
    if weights is None:
        weights = {"V": 0.5, "E": 0.3, "T": 0.2}
    comps = {"V": [], "E": [], "T": [], "D": []}
    for it in evidence:
        s = compute_item_scores(it)
        comps["V"].append(s["V"]) 
        comps["E"].append(s["E"]) 
        comps["T"].append(s["T"]) 
        comps["D"].append(s["D"]) 

    def mean(lst):
        return sum(lst) / len(lst) if lst else 0.0

    Vw = mean(comps["V"]) if comps["V"] else 0.0
    Ew = mean(comps["E"]) if comps["E"] else 0.0
    Tw = mean(comps["T"]) if comps["T"] else 0.0
    Dw = mean(comps["D"]) if comps["D"] else 1.0

    raw = weights["V"] * Vw + weights["E"] * Ew + weights["T"] * Tw
    score = clamp01(raw * Dw)
    return {
        "popularity_score": score,
        "score_components": {"V": Vw, "E": Ew, "T": Tw, "decay_multiplier": Dw},
    }
