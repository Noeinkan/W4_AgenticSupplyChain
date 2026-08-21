"""
UN Comtrade API v2 ingestion.
Fetches bilateral trade flows and detects >20% YoY drops as disruption signals.

Two endpoints, picked automatically:

  * the **public preview** endpoint, which serves the same records with no key at
    all (capped result set, which is fine for anomaly detection on the largest
    bilateral pairs);
  * the **subscriber** endpoint when ``COMTRADE_API_KEY`` is set - free key from
    https://comtradeplus.un.org/ - which lifts the cap.

Detection needs two reference years in the same response: with a single period
every bilateral pair has one record and nothing can be compared. ``PERIODS``
therefore always asks for the two most recent complete years, which trail the
current year by one.
"""

import logging
from datetime import UTC, datetime
from itertools import groupby

import httpx

from orchestrator.config import settings

logger = logging.getLogger(__name__)

# The two endpoints differ by more than a host prefix: the subscriber route has a
# /get/ segment the public preview route does not.
COMTRADE_URL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
COMTRADE_PUBLIC_URL = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"

# Key reporter countries for fashion + electronics (ISO 3-digit codes)
REPORTER_CODES = ["842", "251", "276", "826"]  # USA, France, Germany, UK

# What the throttled keyless endpoint can realistically sustain: the US alone,
# which is the reporter that governs the lanes this catalog models.
PUBLIC_REPORTER_CODES = ["842"]

# The preview endpoint allows roughly one anonymous request a minute.
PUBLIC_REQUEST_SPACING_S = 20.0

# M49 numeric reporter/partner codes -> the ISO2 codes the catalog uses. Covers
# the reporters polled plus the apparel and electronics sourcing nations that
# actually appear in these HS chapters; an unmapped partner still produces an
# anomaly, just labelled by its numeric code.
M49_TO_ISO2: dict[str, str] = {
    "004": "AF", "050": "BD", "056": "BE", "076": "BR", "104": "MM", "116": "KH",
    "124": "CA", "144": "LK", "152": "CL", "156": "CN", "158": "TW", "170": "CO",
    "188": "CR", "203": "CZ", "214": "DO", "222": "SV", "231": "ET", "251": "FR",
    "276": "DE", "320": "GT", "332": "HT", "340": "HN", "344": "HK", "348": "HU",
    "356": "IN", "360": "ID", "364": "IR", "380": "IT", "392": "JP", "400": "JO",
    "404": "KE", "410": "KR", "450": "MG", "458": "MY", "480": "MU", "484": "MX",
    "504": "MA", "528": "NL", "558": "NI", "586": "PK", "604": "PE", "608": "PH",
    "616": "PL", "620": "PT", "642": "RO", "702": "SG", "703": "SK", "704": "VN",
    "710": "ZA", "724": "ES", "757": "CH", "764": "TH", "788": "TN", "792": "TR",
    "818": "EG", "826": "GB", "842": "US",
}

# Key HS codes: fashion (61, 62) + electronics (84, 85)
HS_CODES_FASHION = ["6101", "6104", "6201", "6204"]
HS_CODES_ELECTRONICS = ["8471", "8542", "8517", "8528"]
ALL_HS_CODES = HS_CODES_FASHION + HS_CODES_ELECTRONICS

DROP_THRESHOLD = 0.20
MIN_FLOW_VALUE_USD = 1_000_000


def reference_periods(today: datetime | None = None) -> list[str]:
    """
    The two most recent complete reporting years.

    Comtrade annual data lands well after year end, so the current year is never
    a safe reference: in 2026 this returns ``["2024", "2025"]``.
    """
    year = (today or datetime.now(UTC)).year
    return [str(year - 2), str(year - 1)]


PERIODS = reference_periods()


async def fetch_trade_flows(
    reporter_code: str,
    hs_codes: list[str],
    periods: list[str] | None = None,
) -> list[dict]:
    """
    Fetch bilateral annual trade flows from UN Comtrade API v2.
    Returns raw flow records across every requested period.

    The subscriber endpoint takes several periods in one call; the preview
    endpoint rejects a comma-separated period outright, so the keyless path walks
    the years one request at a time.
    """
    wanted = periods or PERIODS
    if settings.comtrade_api_key:
        return await _fetch_period(reporter_code, hs_codes, ",".join(wanted))

    import asyncio

    flows: list[dict] = []
    for index, period in enumerate(wanted):
        if index:
            await asyncio.sleep(PUBLIC_REQUEST_SPACING_S)
        flows.extend(await _fetch_period(reporter_code, hs_codes, period))
    return flows


async def _fetch_period(reporter_code: str, hs_codes: list[str], period: str) -> list[dict]:
    keyed = bool(settings.comtrade_api_key)
    url = COMTRADE_URL if keyed else COMTRADE_PUBLIC_URL

    params = {
        "typeCode": "C",
        "freqCode": "A",
        "clCode": "HS",
        "period": period,
        "reporterCode": reporter_code,
        "cmdCode": ",".join(hs_codes[:5]),  # API limit: 5 per call
        "flowCode": "M",
    }
    if keyed:
        params["partnerCode"] = "ALL"
        params["subscription-key"] = settings.comtrade_api_key

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 429:
                logger.warning(
                    "Comtrade rate-limited reporter %s period %s; skipping",
                    reporter_code, period,
                )
                return []
            resp.raise_for_status()
            return resp.json().get("data", [])
    except Exception:
        logger.exception(
            "Comtrade fetch failed for reporter %s period %s", reporter_code, period
        )
        return []


def _iso2(code) -> str:
    return M49_TO_ISO2.get(str(code).zfill(3), "")


def detect_trade_anomalies(flows: list[dict]) -> list[dict]:
    """
    Detect >20% YoY drop in any bilateral trade pair.
    Returns anomaly records formatted as event dicts.
    """
    anomalies: list[dict] = []
    key = lambda x: (  # noqa: E731 - grouping key reused for sort and groupby
        str(x.get("reporterCode")),
        str(x.get("partnerCode")),
        str(x.get("cmdCode")),
    )
    for _key, group in groupby(sorted(flows, key=key), key=key):
        records = sorted(list(group), key=lambda x: str(x.get("period", "")))
        if len(records) < 2:
            continue
        latest, prior = records[-1], records[-2]
        if str(latest.get("period")) == str(prior.get("period")):
            continue

        prior_value = float(prior.get("primaryValue") or 0)
        latest_value = float(latest.get("primaryValue") or 0)
        if prior_value <= MIN_FLOW_VALUE_USD:  # Only flag significant trade flows
            continue

        change = (latest_value - prior_value) / prior_value
        if change >= -DROP_THRESHOLD:
            continue

        reporter = _iso2(latest.get("reporterCode"))
        partner = _iso2(latest.get("partnerCode"))
        anomalies.append(
            {
                "title": (
                    f"Trade flow drop {abs(change):.0%}: "
                    f"{reporter or latest.get('reporterCode')} <- "
                    f"{partner or latest.get('partnerCode')} HS{latest.get('cmdCode')}"
                ),
                "content": (
                    f"Reported imports fell {abs(change):.0%} between "
                    f"{prior.get('period')} and {latest.get('period')} "
                    f"(${prior_value:,.0f} -> ${latest_value:,.0f}). "
                    f"Possible tariff, geopolitical or supply disruption on this lane. "
                    f"Source: UN Comtrade annual bilateral flows."
                ),
                "url": "https://comtradeplus.un.org/",
                "event_type": "tariff" if change < -0.40 else "geopolitical",
                "severity": 4 if change < -0.50 else 2,
                "affected_countries": [c for c in (reporter, partner) if c],
                "affected_hs_codes": [str(latest.get("cmdCode", ""))],
                "raw_data": {
                    "prior_period": prior.get("period"),
                    "latest_period": latest.get("period"),
                    "prior_value_usd": prior_value,
                    "latest_value_usd": latest_value,
                    "change": change,
                },
            }
        )
    return anomalies


async def fetch_all_anomalies() -> list[dict]:
    """
    Pull trade flows for all configured reporters and return anomaly events.
    Called by the APScheduler job daily.

    Without a key this is deliberately narrow: the preview endpoint throttles
    anonymous callers to roughly a request a minute, so only the reporters in
    ``PUBLIC_REPORTER_CODES`` are polled, spaced out, and a throttled cycle simply
    yields nothing rather than failing. Set ``COMTRADE_API_KEY`` (free) to widen
    it to every reporter and drop the pacing.
    """
    import asyncio

    keyed = bool(settings.comtrade_api_key)
    reporters = REPORTER_CODES if keyed else PUBLIC_REPORTER_CODES

    all_flows: list[dict] = []
    if keyed:
        results = await asyncio.gather(
            *[fetch_trade_flows(r, ALL_HS_CODES[:5]) for r in reporters],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, list):
                all_flows.extend(r)
    else:
        for index, reporter in enumerate(reporters):
            if index:
                await asyncio.sleep(PUBLIC_REQUEST_SPACING_S)
            all_flows.extend(await fetch_trade_flows(reporter, ALL_HS_CODES[:5]))

    anomalies = detect_trade_anomalies(all_flows)
    logger.info(
        "Comtrade: processed %d flows across %s -> %d anomalies",
        len(all_flows), ",".join(PERIODS), len(anomalies),
    )
    return anomalies
