from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import pandas as pd
from dateutil import parser as dtparser


@dataclass
class SeveritySummary:
    crashes: int
    fires: int
    injuries: int
    deaths: int


def _get_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = payload.get("results") or payload.get("Results") or []
    if isinstance(items, list):
        return [x for x in items if isinstance(x, dict)]
    return []


def summarize_severity(complaints_payload: Dict[str, Any]) -> SeveritySummary:
    items = _get_items(complaints_payload)
    crashes = fires = injuries = deaths = 0

    for c in items:
        crashes += int(bool(c.get("crash") or c.get("Crash") or False))
        fires += int(bool(c.get("fire") or c.get("Fire") or False))

        inj = c.get("numberOfInjuries") or c.get("injuries") or 0
        dth = c.get("numberOfDeaths") or c.get("deaths") or 0
        try:
            injuries += int(inj)
        except Exception:
            pass
        try:
            deaths += int(dth)
        except Exception:
            pass

    return SeveritySummary(crashes=crashes, fires=fires, injuries=injuries, deaths=deaths)


def component_frequency(complaints_payload: Dict[str, Any], top_n: int = 15) -> pd.DataFrame:
    items = _get_items(complaints_payload)
    ctr = Counter()

    for c in items:
        comps = c.get("components") or c.get("Components") or []
        if isinstance(comps, list):
            for comp in comps:
                comp_s = str(comp).strip().upper()
                if comp_s:
                    ctr[comp_s] += 1
        else:
            comp_s = str(comps or "").strip().upper()
            if comp_s:
                ctr[comp_s] += 1

    rows = [{"component": k, "count": v} for k, v in ctr.most_common(top_n)]
    return pd.DataFrame(rows)


def complaints_over_time(complaints_payload: Dict[str, Any], freq: str = "M") -> pd.DataFrame:
    items = _get_items(complaints_payload)
    dates = []
    for c in items:
        raw = c.get("dateComplaintFiled") or c.get("dateFiled") or c.get("DateComplaintFiled")
        if not raw:
            continue
        try:
            d = dtparser.parse(str(raw)).date()
            dates.append(pd.Timestamp(d))
        except Exception:
            continue

    if not dates:
        return pd.DataFrame(columns=["period", "count"])

    s = pd.Series(1, index=pd.to_datetime(dates))
    if freq == "Y":
        grouped = s.resample("Y").sum()
        periods = grouped.index.strftime("%Y")
    else:
        grouped = s.resample("M").sum()
        periods = grouped.index.strftime("%Y-%m")

    return pd.DataFrame({"period": list(periods), "count": grouped.values})


def complaints_by_state(complaints_payload: Dict[str, Any]) -> pd.DataFrame:
    items = _get_items(complaints_payload)
    ctr = Counter()

    name_to_abbrev = {
        "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
        "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE",
        "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID",
        "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
        "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
        "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
        "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
        "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
        "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
        "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
        "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT",
        "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV",
        "WISCONSIN": "WI", "WYOMING": "WY", "DISTRICT OF COLUMBIA": "DC",
    }

    valid_abbrevs = set(name_to_abbrev.values())

    def normalize_state(raw: Any) -> str:
        if not raw:
            return ""
        s = str(raw).strip().upper()

        if len(s) == 2 and s in valid_abbrevs:
            return s

        if s in name_to_abbrev:
            return name_to_abbrev[s]

        if "," in s:
            parts = [p.strip() for p in s.split(",") if p.strip()]
            if parts:
                last = parts[-1]
                if len(last) == 2 and last in valid_abbrevs:
                    return last
                if last in name_to_abbrev:
                    return name_to_abbrev[last]

        return ""

    possible_keys = [
        "state", "State", "locationState", "LocationState",
        "consumerState", "ConsumerState",
        "incidentState", "IncidentState",
        "location", "Location",
        "city", "City",
    ]

    for c in items:
        raw_state = None
        for k in possible_keys:
            if c.get(k):
                raw_state = c.get(k)
                break

        st_abbrev = normalize_state(raw_state)
        if st_abbrev:
            ctr[st_abbrev] += 1

    rows = [{"state": k, "count": v} for k, v in ctr.most_common()]
    return pd.DataFrame(rows)


def simple_case_strength_label(recalls_count: int, complaints_count: int, severity: SeveritySummary) -> Tuple[str, str]:
    score = 0
    reasons = []

    if recalls_count > 0:
        score += 2
        reasons.append(f"{recalls_count} recall(s) found")

    if complaints_count >= 25:
        score += 2
        reasons.append("high complaint volume")
    elif complaints_count >= 10:
        score += 1
        reasons.append("moderate complaint volume")

    if severity.deaths > 0:
        score += 3
        reasons.append("death(s) reported")
    if severity.injuries > 0:
        score += 2
        reasons.append("injuries reported")
    if severity.fires > 0:
        score += 2
        reasons.append("fire(s) reported")
    if severity.crashes > 0:
        score += 1
        reasons.append("crash(es) reported")

    if score >= 6:
        return "Strong signal", ", ".join(reasons) or "multiple indicators"
    if score >= 3:
        return "Moderate signal", ", ".join(reasons) or "some indicators"
    return "Low signal", ", ".join(reasons) or "limited indicators"
