"""
UN Comtrade API v2 ingestion.
Free subscription key: https://comtradeplus.un.org/
Fetches bilateral trade flows and detects >20% YoY drops as disruption signals.
"""

import logging
from itertools import groupby

import httpx

from orchestrator.config import settings

logger = logging.getLogger(__name__)

COMTRADE_BASE = "https://comtradeapi.un.org/data/v1"

# Key reporter countries for fashion + electronics (ISO 3-digit codes)
REPORTER_CODES = ["842", "251", "276", "826"]  # USA, France, Germany, UK

# Key HS codes: fashion (61, 62) + electronics (84, 85)
HS_CODES_FASHION = ["6101", "6104", "6201", "6204"]
HS_CODES_ELECTRONICS = ["8471", "8542", "8517", "8528"]
ALL_HS_CODES = HS_CODES_FASHION + HS_CODES_ELECTRONICS


async def fetch_trade_flows(
    reporter_code: str,
    hs_codes: list[str],
    period: str = "2024",
) -> list[dict]:
    """
    Fetch bilateral annual trade flows from UN Comtrade API v2.
    Returns raw flow records.
    """
    if not settings.comtrade_api_key:
        logger.warning("COMTRADE_API_KEY not set — skipping Comtrade fetch")
        return []

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(
                f"{COMTRADE_BASE}/get/C/A/HS",
                params={
                    "typeCode": "C",
                    "freqCode": "A",
                    "clCode": "HS",
                    "period": period,
                    "reporterCode": reporter_code,
                    "cmdCode": ",".join(hs_codes[:5]),  # API limit: 5 per call
                    "flowCode": "M,X",
                    "partnerCode": "ALL",
                    "subscription-key": settings.comtrade_api_key,
                },
            )
            resp.raise_for_status()
            return resp.json().get("data", [])
    except Exception:
        logger.exception("Comtrade fetch failed for reporter %s", reporter_code)
        return []


def detect_trade_anomalies(flows: list[dict]) -> list[dict]:
    """
    Detect >20% YoY drop in any bilateral trade pair.
    Returns anomaly records formatted as event dicts.
    """
    anomalies: list[dict] = []
    sorted_flows = sorted(
        flows, key=lambda x: (x.get("reporterCode"), x.get("partnerCode"), x.get("cmdCode"))
    )
    for _key, group in groupby(
        sorted_flows,
        key=lambda x: (x.get("reporterCode"), x.get("partnerCode"), x.get("cmdCode")),
    ):
        records = sorted(list(group), key=lambda x: x.get("period", ""))
        if len(records) < 2:
            continue
        latest, prior = records[-1], records[-2]
        prior_value = float(prior.get("primaryValue") or 0)
        latest_value = float(latest.get("primaryValue") or 0)
        if prior_value > 1_000_000:  # Only flag significant trade flows (>$1M)
            change = (latest_value - prior_value) / prior_value
            if change < -0.20:
                anomalies.append(
                    {
                        "title": (
                            f"Trade flow drop: {latest.get('reporterCode')} ↔ "
                            f"{latest.get('partnerCode')} HS{latest.get('cmdCode')}"
                        ),
                        "content": (
                            f"Trade flow fell {abs(change):.0%} YoY "
                            f"(${prior_value:,.0f} → ${latest_value:,.0f}). "
                            f"Possible tariff, geopolitical, or supply disruption."
                        ),
                        "url": "https://comtradeplus.un.org/",
                        "event_type": "tariff" if change < -0.40 else "geopolitical",
                        "severity": 4 if change < -0.50 else 2,
                        "affected_countries": [
                            latest.get("reporterCode", ""),
                            latest.get("partnerCode", ""),
                        ],
                        "affected_hs_codes": [latest.get("cmdCode", "")],
                    }
                )
    return anomalies


async def fetch_all_anomalies() -> list[dict]:
    """
    Pull trade flows for all configured reporters and return anomaly events.
    Called by the APScheduler job daily.
    """
    import asyncio

    all_flows: list[dict] = []
    results = await asyncio.gather(
        *[
            fetch_trade_flows(reporter, ALL_HS_CODES[:5])
            for reporter in REPORTER_CODES
        ],
        return_exceptions=True,
    )
    for r in results:
        if isinstance(r, list):
            all_flows.extend(r)

    anomalies = detect_trade_anomalies(all_flows)
    logger.info(
        "Comtrade: processed %d flows → %d anomalies", len(all_flows), len(anomalies)
    )
    return anomalies
