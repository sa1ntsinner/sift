import json

import pytest

from conftest import FIXTURES
from steamsift import region
from steamsift.region import PriceFormat

REGIONS = sorted(p.stem.split("_")[1] for p in FIXTURES.glob("getitems_*.json"))


def test_every_store_country_has_names_and_a_price_sample():
    data = region._data()
    stores = [c for c, i in data.items() if i["store"]]
    assert len(stores) >= 240
    for code in stores:
        assert data[code]["en"] and data[code]["ru"] and data[code]["sample"], code


def test_usd_price_groups_are_distinct_regions():
    assert region.group("TR") == region.group("EG") == "MENA-USD"
    assert region.group("AZ") == region.group("UZ") == "CIS-USD"
    assert region.group("AR") == "LATAM-USD"
    assert region.group("PK") == "SASIA-USD"
    assert region.group("US") == "USD"
    assert region.group("KZ") is None and region.currency_marker("KZ") == "₸"


def test_sanctioned_countries_have_no_store():
    for code in ("IR", "CU", "KP"):
        assert region.info(code) and not region.has_store(code)


def test_labels_are_localised():
    assert region.label("TR", "ru") == "Турция · MENA-USD"
    assert region.label("DE", "en") == "Germany · €"
    assert region.label("US", "en").endswith("USD")


@pytest.mark.parametrize("query,expected", [("kz", ["KZ"]), ("Казахстан", ["KZ"]), ("germ", ["DE"]),
                                            ("турц", ["TR"])])
def test_country_search(query, expected):
    assert region.search(query, "ru")[: len(expected)] == expected


@pytest.mark.parametrize("cc", REGIONS)
def test_formatter_reproduces_every_steam_price(cc):
    """Learned from one sample, the formatter must render every real price exactly like Steam."""
    pf = region.price_format(cc)
    items = json.loads((FIXTURES / f"getitems_{cc}.json").read_text(encoding="utf-8"))["response"]["store_items"]
    checked = 0
    for it in items:
        o = it.get("best_purchase_option") or {}
        for fk, ck in (("formatted_final_price", "final_price_in_cents"),
                       ("formatted_original_price", "original_price_in_cents")):
            if o.get(fk) and o.get(ck):
                assert pf.format(int(o[ck])) == o[fk]
                checked += 1
    assert checked


@pytest.mark.parametrize("sample,cents,amount,expected", [
    ("$39.99", 3999, 15, "$15.00"),
    ("14 549,00₸", 1454900, 1500, "1 500,00₸"),
    ("¥3,990", 399000, 2000, "¥2,000"),
    ("850.000₫", 85000000, 120000, "120.000₫"),
    ("3599 руб", 359900, 1500, "1500 руб"),
    ("CHF 39.90", 3990, 25, "CHF 25.00"),
])
def test_budget_amounts_in_local_format(sample, cents, amount, expected):
    assert PriceFormat.learn(sample, cents).amount(amount) == expected
