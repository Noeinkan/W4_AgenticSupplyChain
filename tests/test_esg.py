"""
Unit tests for the ESG scoring engine — no DB required.
"""

from orchestrator.esg.calculator import (
    _score_environmental,
    _score_governance,
    _score_social,
    score_portfolio,
    score_supplier,
)


SUPPLIER_HIGH_ESG = {
    "id": "s1",
    "name": "GreenFactory",
    "country_code": "DE",
    "certifications": {"ISO14001": True, "RE100": True, "SA8000": True, "ISO37001": True},
}

SUPPLIER_LOW_ESG = {
    "id": "s2",
    "name": "BasicFactory",
    "country_code": "BD",
    "certifications": {},
}

LOW_CO2_ROUTES = [{"co2_kg_per_unit": 0.3}]
HIGH_CO2_ROUTES = [{"co2_kg_per_unit": 8.0}]


def test_environmental_high_certs_low_co2():
    score = _score_environmental({"ISO14001": True, "RE100": True, "SBTi": True}, avg_co2=0.3)
    assert score >= 90


def test_environmental_no_certs_high_co2():
    score = _score_environmental({}, avg_co2=8.0)
    assert score < 50


def test_social_good_country_with_certs():
    score = _score_social({"SA8000": True, "WRAP": True}, "DE")
    assert score >= 75


def test_social_poor_country_no_certs():
    score = _score_social({}, "BD")
    assert score < 55


def test_governance_germany():
    score = _score_governance({}, "DE")
    assert score >= 85


def test_governance_bangladesh():
    score = _score_governance({}, "BD")
    assert score < 40


def test_score_supplier_composite_ordering():
    high = score_supplier(SUPPLIER_HIGH_ESG, LOW_CO2_ROUTES)
    low = score_supplier(SUPPLIER_LOW_ESG, HIGH_CO2_ROUTES)
    assert high["composite_score"] > low["composite_score"]
    assert 0 <= low["composite_score"] <= 100
    assert 0 <= high["composite_score"] <= 100


def test_score_portfolio_weighted_average():
    allocation = {"s1": 700.0, "s2": 300.0}
    suppliers = [SUPPLIER_HIGH_ESG, SUPPLIER_LOW_ESG]
    routes = [
        {"id": "r1", "origin_supplier_id": "s1", "co2_kg_per_unit": 0.3},
        {"id": "r2", "origin_supplier_id": "s2", "co2_kg_per_unit": 8.0},
    ]
    portfolio = score_portfolio(allocation, suppliers, routes)
    assert 0 < portfolio["composite"] < 100
    # Heavy weighting toward high-ESG supplier should pull composite up
    all_low = score_portfolio({"s1": 0.0, "s2": 1000.0}, suppliers, routes)
    all_high = score_portfolio({"s1": 1000.0, "s2": 0.0}, suppliers, routes)
    assert portfolio["composite"] > all_low["composite"]
    assert portfolio["composite"] < all_high["composite"]
