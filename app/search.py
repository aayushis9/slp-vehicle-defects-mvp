import re
import pandas as pd


def _normalize(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def keyword_search(df: pd.DataFrame, query: str, top_k: int = 50) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    q = _normalize(query)
    if not q:
        return df.head(top_k)

    terms = [t for t in q.split(" ") if t]
    if not terms:
        return df.head(top_k)

    def score(summary: str) -> int:
        s = _normalize(summary)
        return sum(1 for t in terms if t in s)

    scored = df.copy()
    scored["match_score"] = scored["summary"].fillna("").apply(score)
    scored = scored[scored["match_score"] > 0].sort_values(
        by=["match_score", "deaths", "injuries", "fire", "crash"],
        ascending=[False, False, False, False, False],
    )
    return scored.head(top_k)
