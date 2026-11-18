import json
from pathlib import Path

import pytest

from src.ingest.eurostat import REQUIRED_KEYS, check_filters, headline_rows, load_indicators, parse_jsonstat

FIXTURES = Path(__file__).parent / "fixtures" / "eurostat"
INDICATORS = load_indicators()


def as_list(v):
    return [v] if isinstance(v, str) else list(v)


def test_config_has_the_five_datasets():
    assert {e["code"] for e in INDICATORS.values()} == {
        "une_rt_m", "prc_hicp_minr", "sts_inpr_m", "sts_trtu_m", "ei_bsco_m",
    }


@pytest.mark.parametrize("name", INDICATORS)
def test_entry_has_required_keys(name):
    entry = INDICATORS[name]
    for key in REQUIRED_KEYS:
        assert entry[key], f"{name}: {key} is empty"
    assert {"DE", "FR", "IT", "NL", "PL", "EA21"} <= set(entry["filters"]["geo"])


@pytest.mark.parametrize("name", INDICATORS)
def test_headline_is_consistent_with_filters(name):
    filters, headline = INDICATORS[name]["filters"], INDICATORS[name]["headline"]
    for dim, code in headline.items():
        assert code in as_list(filters[dim]), f"{name}: headline {dim}={code} is filtered out"
    # Any non-geo dimension requested with several codes must be pinned by the headline.
    multi = {d for d, v in filters.items() if d != "geo" and len(as_list(v)) > 1}
    assert multi <= set(headline), f"{name}: headline leaves {multi - set(headline)} open"


@pytest.fixture(params=list(INDICATORS))
def parsed(request):
    entry = INDICATORS[request.param]
    payload = json.loads((FIXTURES / f"{entry['code']}.json").read_text(encoding="utf-8"))
    return entry, payload, parse_jsonstat(payload, indicator_code=entry["code"])


def test_headline_selects_one_series_per_geo_and_time(parsed):
    entry, _, df = parsed
    head = headline_rows(df, entry["headline"])
    assert not head.empty
    counts = head.groupby(["geo", "time"]).size()
    assert (counts == 1).all(), counts[counts != 1]
    assert set(head["geo"]) == set(df["geo"])


def test_fixture_dimensions_match_config(parsed):
    entry, payload, _ = parsed
    problems = check_filters(payload, entry["filters"])
    assert problems == []


def test_requested_dimensions_exclude_non_breakdown_columns():
    from src.load.dbt_seeds import requested_dimensions

    dims = requested_dimensions(INDICATORS)
    assert not {d for _, d in dims} & {"geo", "unit", "s_adj"}
    assert ("industrial_production", "indic_bt") in dims  # requested though dropped as constant
    assert {n for n, _ in dims} == set(INDICATORS)
