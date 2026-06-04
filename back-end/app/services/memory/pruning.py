"""Prune profile dict to max_bytes by dropping the least-recently-updated
top-level keys until the JSON fits."""
import json


def prune_profile(
    data: dict, ts_map: dict[str, float], max_bytes: int,
) -> dict:
    if not data:
        return data
    encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
    if len(encoded) <= max_bytes:
        return data

    def score(top_key: str) -> float:
        best = 0.0
        for k, ts in ts_map.items():
            if k == top_key or k.startswith(top_key + "."):
                best = max(best, ts)
        return best

    keys_sorted = sorted(data.keys(), key=score)  # oldest first
    pruned = dict(data)
    for k in keys_sorted:
        pruned.pop(k)
        encoded = json.dumps(pruned, ensure_ascii=False).encode("utf-8")
        if len(encoded) <= max_bytes:
            return pruned
    return pruned
