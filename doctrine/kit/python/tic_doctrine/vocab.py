"""Load the kit's vocabulary files.

The vocab folder sits two levels above this package, both in the kit repo
(tic-doctrine/vocab) and in a vendored copy (doctrine/kit/vocab).
"""

import json
from functools import cache
from pathlib import Path

VOCAB_DIR = Path(__file__).resolve().parents[2] / "vocab"


@cache
def load(name: str) -> dict:
    with open(VOCAB_DIR / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


def enum(name: str) -> set[str]:
    """Allowed values of one closed list in enums.json."""
    return set(load("enums")[name]["values"])


def framework(name: str) -> dict:
    return load("frameworks")[name]


def ncf() -> dict:
    return load("infrastructure")["ncf"]


def sectors() -> dict:
    return load("infrastructure")["sectors"]


def lifelines() -> dict:
    return load("infrastructure")["lifelines"]


def ladders() -> dict:
    return load("grading")["response_stage"]["ladders"]


def admiralty() -> dict:
    return load("grading")["admiralty"]


def derive_sectors(ncf_ids) -> list[str]:
    """Sectors implied by a list of National Critical Function ids, sorted."""
    table = ncf()
    out = set()
    for f in ncf_ids or []:
        out.update(table[f]["sectors"])
    return sorted(out)


def derive_lifelines(ncf_ids) -> list[str]:
    table = ncf()
    out = set()
    for f in ncf_ids or []:
        out.update(table[f]["lifelines"])
    return sorted(out)
