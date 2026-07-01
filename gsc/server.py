"""
Google Search Console — multi-tenant public version.
Uses per-user OAuth credentials via MCP OAuth 2.0 flow.
"""

import sys, os  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from mcp.server.fastmcp import FastMCP
from googleapiclient.discovery import build

from shared.user_creds import get_current_google_credentials
from shared.config import GOOGLE_SCOPES

# ═══════════════════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════════════════

mcp = FastMCP("Google Search Console")


# ═══════════════════════════════════════════════════════════════════════════════
# Clients
# ═══════════════════════════════════════════════════════════════════════════════

def _credentials():
    return get_current_google_credentials(GOOGLE_SCOPES["gsc"])


def _service():
    return build("searchconsole", "v1", credentials=_credentials(),
                 cache_discovery=False)


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _resolve_date(date_str: str) -> str:
    """Convert relative date strings to YYYY-MM-DD.

    Supports: 'today', 'yesterday', 'NdaysAgo' (e.g. '7daysAgo', '28daysAgo'),
    or a literal YYYY-MM-DD string.
    """
    today = datetime.now()
    if date_str == "today":
        return today.strftime("%Y-%m-%d")
    if date_str == "yesterday":
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")
    if date_str.endswith("daysAgo"):
        days = int(date_str.replace("daysAgo", ""))
        return (today - timedelta(days=days)).strftime("%Y-%m-%d")
    return date_str


def _build_filter_groups(filters) -> list[dict]:
    """Build dimensionFilterGroups from a simplified config.

    Formats:
        Single filter:
            {"dimension": "query", "operator": "contains", "expression": "seo"}

        AND group (list of filters):
            [
                {"dimension": "query", "operator": "contains", "expression": "seo"},
                {"dimension": "country", "operator": "equals", "expression": "usa"}
            ]

        Multiple AND groups (OR between groups):
            [
                [{"dimension": "query", "operator": "contains", "expression": "seo"}],
                [{"dimension": "query", "operator": "contains", "expression": "sem"}]
            ]

    Operators: contains, equals, notContains, notEquals,
               includingRegex, excludingRegex
    Dimensions: query, page, country, device, searchAppearance
    """
    if not filters:
        return []

    if isinstance(filters, dict):
        return [{"groupType": "and", "filters": [filters]}]

    if isinstance(filters, list):
        if not filters:
            return []
        if isinstance(filters[0], list):
            return [{"groupType": "and", "filters": g} for g in filters]
        if isinstance(filters[0], dict):
            return [{"groupType": "and", "filters": filters}]

    return []


def _query(
    site_url: str,
    dimensions: list[str] | None = None,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    row_limit: int = 1000,
    start_row: int = 0,
    search_type: str = "web",
    filters=None,
    aggregation_type: str = "auto",
    data_state: str = "final",
) -> dict:
    """Execute a searchAnalytics.query request."""
    if not site_url:
        raise ValueError("site_url is required. Use list_sites to find your verified sites.")
    body: dict = {
        "startDate": _resolve_date(start_date),
        "endDate": _resolve_date(end_date),
        "rowLimit": min(row_limit, 25000),
        "startRow": start_row,
        "type": search_type,
        "aggregationType": aggregation_type,
        "dataState": data_state,
    }
    if dimensions:
        body["dimensions"] = dimensions
    if filters:
        body["dimensionFilterGroups"] = _build_filter_groups(filters)

    return _service().searchanalytics().query(
        siteUrl=site_url, body=body
    ).execute()


def _format_rows(response: dict, dimensions: list[str] | None = None) -> list[dict]:
    """Convert API response rows into readable dicts."""
    rows = []
    for row in response.get("rows", []):
        d = {}
        keys = row.get("keys", [])
        if dimensions:
            for i, dim in enumerate(dimensions):
                d[dim] = keys[i] if i < len(keys) else None
        else:
            for i, key in enumerate(keys):
                d[f"key_{i}"] = key
        d["clicks"] = row.get("clicks", 0)
        d["impressions"] = row.get("impressions", 0)
        d["ctr"] = round(row.get("ctr", 0), 4)
        d["position"] = round(row.get("position", 0), 2)
        rows.append(d)
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# 1. CORE / GENERIC TOOLS
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def search_analytics(
    site_url: str,
    dimensions: list[str] | None = None,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    row_limit: int = 1000,
    start_row: int = 0,
    search_type: str = "web",
    filters=None,
    aggregation_type: str = "auto",
    data_state: str = "final",
) -> dict:
    """Run a custom Search Console query with full control over all parameters.

    Args:
        dimensions: Dimensions to group by. Options: date, query, page, country,
            device, searchAppearance. Max 3 at a time. Example: ["query", "page"]
        start_date: YYYY-MM-DD or relative ("28daysAgo", "7daysAgo", "yesterday")
        end_date: YYYY-MM-DD or relative. Note: data has 2-3 day delay.
        row_limit: Max rows (default 1000, max 25000)
        start_row: Row offset for pagination (default 0)
        search_type: Type of search results. Options:
            "web" (default), "image", "video", "news", "discover", "googleNews"
        filters: Dimension filter config. Formats:
            Single: {"dimension": "query", "operator": "contains", "expression": "keyword"}
            AND group: [filter1, filter2]
            OR groups: [[filter1], [filter2]]
            Operators: contains, equals, notContains, notEquals,
                       includingRegex, excludingRegex
            Dimensions: query, page, country, device, searchAppearance
        aggregation_type: "auto" (default), "byPage", or "byProperty"
        data_state: "final" (default, verified data) or "all" (includes fresh/preliminary)
    """
    dims = dimensions or []
    response = _query(
        site_url=site_url,
        dimensions=dims or None,
        start_date=start_date,
        end_date=end_date,
        row_limit=row_limit,
        start_row=start_row,
        search_type=search_type,
        filters=filters,
        aggregation_type=aggregation_type,
        data_state=data_state,
    )
    rows = _format_rows(response, dims or None)
    return {
        "rows": rows,
        "row_count": len(rows),
        "response_aggregation_type": response.get("responseAggregationType"),
    }


@mcp.tool()
def search_analytics_comparison(
    site_url: str,
    dimensions: list[str],
    period1_start: str = "56daysAgo",
    period1_end: str = "29daysAgo",
    period2_start: str = "28daysAgo",
    period2_end: str = "3daysAgo",
    row_limit: int = 1000,
    search_type: str = "web",
    filters=None,
) -> dict:
    """Compare two date ranges side by side for any dimensions.

    Returns rows with period1 and period2 metrics plus calculated changes.

    Args:
        dimensions: Dimensions to group by (e.g. ["query"], ["page"])
            Do NOT include "date" as a dimension.
        period1_start: First (older) period start date
        period1_end: First period end date
        period2_start: Second (newer) period start date
        period2_end: Second period end date
        row_limit: Max rows per period (default 1000)
        search_type: "web", "image", "video", "news", "discover", "googleNews"
        filters: Dimension filter config (see search_analytics for syntax)
    """
    r1 = _query(
        site_url=site_url,
        dimensions=dimensions, start_date=period1_start, end_date=period1_end,
        row_limit=row_limit, search_type=search_type, filters=filters,
    )
    r2 = _query(
        site_url=site_url,
        dimensions=dimensions, start_date=period2_start, end_date=period2_end,
        row_limit=row_limit, search_type=search_type, filters=filters,
    )

    rows1 = {tuple(r.get("keys", [])): r for r in r1.get("rows", [])}
    rows2 = {tuple(r.get("keys", [])): r for r in r2.get("rows", [])}
    all_keys = set(rows1.keys()) | set(rows2.keys())

    results = []
    for key in all_keys:
        d = {}
        for i, dim in enumerate(dimensions):
            d[dim] = key[i] if i < len(key) else None

        p1 = rows1.get(key, {})
        p2 = rows2.get(key, {})

        d["period1_clicks"] = p1.get("clicks", 0)
        d["period1_impressions"] = p1.get("impressions", 0)
        d["period1_ctr"] = round(p1.get("ctr", 0), 4)
        d["period1_position"] = round(p1.get("position", 0), 2)

        d["period2_clicks"] = p2.get("clicks", 0)
        d["period2_impressions"] = p2.get("impressions", 0)
        d["period2_ctr"] = round(p2.get("ctr", 0), 4)
        d["period2_position"] = round(p2.get("position", 0), 2)

        d["clicks_change"] = d["period2_clicks"] - d["period1_clicks"]
        d["impressions_change"] = d["period2_impressions"] - d["period1_impressions"]
        d["position_change"] = round(d["period1_position"] - d["period2_position"], 2)

        results.append(d)

    results.sort(key=lambda x: x["period2_clicks"], reverse=True)

    return {
        "rows": results[:row_limit],
        "row_count": len(results),
        "period1": f"{_resolve_date(period1_start)} to {_resolve_date(period1_end)}",
        "period2": f"{_resolve_date(period2_start)} to {_resolve_date(period2_end)}",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PERFORMANCE OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_performance_overview(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    search_type: str = "web",
) -> list[dict]:
    """Get daily performance overview: clicks, impressions, CTR, position.

    Args:
        start_date: Start date (YYYY-MM-DD or "28daysAgo", "7daysAgo")
        end_date: End date (YYYY-MM-DD or "3daysAgo", "yesterday")
        search_type: "web", "image", "video", "news", "discover", "googleNews"
    """
    response = _query(
        site_url=site_url,
        dimensions=["date"],
        start_date=start_date,
        end_date=end_date,
        row_limit=25000,
        search_type=search_type,
    )
    rows = _format_rows(response, ["date"])
    rows.sort(key=lambda x: x["date"])
    return rows


@mcp.tool()
def get_performance_summary(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    search_type: str = "web",
) -> dict:
    """Get aggregated performance summary for a period: total clicks, impressions, avg CTR, avg position.

    Args:
        start_date: Start date
        end_date: End date
        search_type: "web", "image", "video", "news", "discover", "googleNews"
    """
    response = _query(
        site_url=site_url,
        dimensions=None,
        start_date=start_date,
        end_date=end_date,
        search_type=search_type,
    )
    rows = response.get("rows", [])
    if rows:
        row = rows[0]
        return {
            "total_clicks": row.get("clicks", 0),
            "total_impressions": row.get("impressions", 0),
            "average_ctr": round(row.get("ctr", 0), 4),
            "average_position": round(row.get("position", 0), 2),
            "period": f"{_resolve_date(start_date)} to {_resolve_date(end_date)}",
        }
    return {
        "total_clicks": 0,
        "total_impressions": 0,
        "average_ctr": 0,
        "average_position": 0,
        "period": f"{_resolve_date(start_date)} to {_resolve_date(end_date)}",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 3. QUERIES
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_top_queries(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    limit: int = 50,
    search_type: str = "web",
    filters=None,
) -> list[dict]:
    """Get top search queries by clicks.

    Args:
        start_date: Start date
        end_date: End date
        limit: Max rows (default 50)
        search_type: "web", "image", "video", "news", "discover", "googleNews"
        filters: Optional dimension filters (see search_analytics for syntax)
    """
    response = _query(
        site_url=site_url,
        dimensions=["query"],
        start_date=start_date,
        end_date=end_date,
        row_limit=limit,
        search_type=search_type,
        filters=filters,
    )
    return _format_rows(response, ["query"])


@mcp.tool()
def get_queries_for_page(
    site_url: str,
    page_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    limit: int = 100,
    search_type: str = "web",
) -> list[dict]:
    """Get all search queries driving traffic to a specific page.

    Args:
        page_url: Full URL or URL path to filter by.
            Use full URL for exact match: "https://example.com/page"
            Use partial path with contains operator for broader match.
        start_date: Start date
        end_date: End date
        limit: Max rows (default 100)
        search_type: "web", "image", "video"
    """
    response = _query(
        site_url=site_url,
        dimensions=["query"],
        start_date=start_date,
        end_date=end_date,
        row_limit=limit,
        search_type=search_type,
        filters={"dimension": "page", "operator": "contains", "expression": page_url},
    )
    return _format_rows(response, ["query"])


@mcp.tool()
def get_query_trend(
    site_url: str,
    query_text: str,
    start_date: str = "90daysAgo",
    end_date: str = "3daysAgo",
    match_type: str = "equals",
    search_type: str = "web",
) -> list[dict]:
    """Get daily trend for a specific search query over time.

    Args:
        query_text: The search query to track
        start_date: Start date (default 90 days for trend visibility)
        end_date: End date
        match_type: "equals" (exact match) or "contains" (partial match)
        search_type: "web", "image", "video"
    """
    response = _query(
        site_url=site_url,
        dimensions=["date"],
        start_date=start_date,
        end_date=end_date,
        row_limit=25000,
        search_type=search_type,
        filters={"dimension": "query", "operator": match_type, "expression": query_text},
    )
    rows = _format_rows(response, ["date"])
    rows.sort(key=lambda x: x["date"])
    return rows


@mcp.tool()
def get_branded_queries(
    site_url: str,
    brand_terms: list[str],
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    limit: int = 100,
    search_type: str = "web",
) -> dict:
    """Analyze branded vs non-branded query performance.

    Fetches queries containing any of the brand terms (branded) and
    queries not containing any brand terms (non-branded).

    Args:
        brand_terms: List of brand-related terms (e.g. ["aihomedesign", "ai home design"])
        start_date: Start date
        end_date: End date
        limit: Max rows per group
        search_type: "web", "image", "video"
    """
    regex = "|".join(brand_terms)

    branded_response = _query(
        site_url=site_url,
        dimensions=["query"],
        start_date=start_date,
        end_date=end_date,
        row_limit=limit,
        search_type=search_type,
        filters={"dimension": "query", "operator": "includingRegex", "expression": regex},
    )
    non_branded_response = _query(
        site_url=site_url,
        dimensions=["query"],
        start_date=start_date,
        end_date=end_date,
        row_limit=limit,
        search_type=search_type,
        filters={"dimension": "query", "operator": "excludingRegex", "expression": regex},
    )

    branded_rows = branded_response.get("rows", [])
    non_branded_rows = non_branded_response.get("rows", [])

    branded_clicks = sum(r.get("clicks", 0) for r in branded_rows)
    branded_impressions = sum(r.get("impressions", 0) for r in branded_rows)
    non_branded_clicks = sum(r.get("clicks", 0) for r in non_branded_rows)
    non_branded_impressions = sum(r.get("impressions", 0) for r in non_branded_rows)

    return {
        "branded": {
            "total_clicks": branded_clicks,
            "total_impressions": branded_impressions,
            "average_ctr": round(branded_clicks / branded_impressions, 4) if branded_impressions else 0,
            "query_count": len(branded_rows),
            "top_queries": _format_rows(branded_response, ["query"])[:20],
        },
        "non_branded": {
            "total_clicks": non_branded_clicks,
            "total_impressions": non_branded_impressions,
            "average_ctr": round(non_branded_clicks / non_branded_impressions, 4) if non_branded_impressions else 0,
            "query_count": len(non_branded_rows),
            "top_queries": _format_rows(non_branded_response, ["query"])[:20],
        },
    }


@mcp.tool()
def get_query_opportunities(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    min_impressions: int = 100,
    max_ctr: float = 0.03,
    limit: int = 50,
    search_type: str = "web",
) -> list[dict]:
    """Find query opportunities: high impressions but low CTR.

    These are queries where your site appears in search results often
    but users rarely click — candidates for title/description optimization.

    Args:
        start_date: Start date
        end_date: End date
        min_impressions: Minimum impressions threshold (default 100)
        max_ctr: Maximum CTR threshold (default 0.03 = 3%)
        limit: Max rows to return (default 50)
        search_type: "web", "image", "video"
    """
    response = _query(
        site_url=site_url,
        dimensions=["query"],
        start_date=start_date,
        end_date=end_date,
        row_limit=5000,
        search_type=search_type,
    )
    rows = _format_rows(response, ["query"])
    filtered = [
        r for r in rows
        if r["impressions"] >= min_impressions and r["ctr"] <= max_ctr
    ]
    filtered.sort(key=lambda x: x["impressions"], reverse=True)
    return filtered[:limit]


@mcp.tool()
def get_low_hanging_fruit(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    min_position: float = 4.0,
    max_position: float = 20.0,
    min_impressions: int = 50,
    limit: int = 50,
    search_type: str = "web",
) -> list[dict]:
    """Find low-hanging fruit: queries ranking on positions 4-20 with decent impressions.

    These are near-first-page or lower-first-page queries that could
    reach top positions with content optimization.

    Args:
        start_date: Start date
        end_date: End date
        min_position: Minimum average position (default 4.0)
        max_position: Maximum average position (default 20.0)
        min_impressions: Minimum impressions (default 50)
        limit: Max rows (default 50)
        search_type: "web", "image", "video"
    """
    response = _query(
        site_url=site_url,
        dimensions=["query"],
        start_date=start_date,
        end_date=end_date,
        row_limit=5000,
        search_type=search_type,
    )
    rows = _format_rows(response, ["query"])
    filtered = [
        r for r in rows
        if min_position <= r["position"] <= max_position
        and r["impressions"] >= min_impressions
    ]
    filtered.sort(key=lambda x: x["impressions"], reverse=True)
    return filtered[:limit]


@mcp.tool()
def get_long_tail_queries(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    min_words: int = 4,
    limit: int = 100,
    search_type: str = "web",
) -> list[dict]:
    """Find long-tail queries (4+ words) — often high-intent, low-competition.

    Args:
        start_date: Start date
        end_date: End date
        min_words: Minimum number of words in query (default 4)
        limit: Max rows (default 100)
        search_type: "web", "image", "video"
    """
    response = _query(
        site_url=site_url,
        dimensions=["query"],
        start_date=start_date,
        end_date=end_date,
        row_limit=10000,
        search_type=search_type,
    )
    rows = _format_rows(response, ["query"])
    filtered = [r for r in rows if len(r["query"].split()) >= min_words]
    filtered.sort(key=lambda x: x["clicks"], reverse=True)
    return filtered[:limit]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. PAGES
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_top_pages(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    limit: int = 50,
    search_type: str = "web",
    filters=None,
) -> list[dict]:
    """Get top pages by clicks.

    Args:
        start_date: Start date
        end_date: End date
        limit: Max rows (default 50)
        search_type: "web", "image", "video", "news", "discover", "googleNews"
        filters: Optional dimension filters (see search_analytics for syntax)
    """
    response = _query(
        site_url=site_url,
        dimensions=["page"],
        start_date=start_date,
        end_date=end_date,
        row_limit=limit,
        search_type=search_type,
        filters=filters,
    )
    return _format_rows(response, ["page"])


@mcp.tool()
def get_pages_for_query(
    site_url: str,
    query_text: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    limit: int = 50,
    match_type: str = "equals",
    search_type: str = "web",
) -> list[dict]:
    """Get all pages ranking for a specific query — useful for cannibalization checks.

    Args:
        query_text: The search query
        start_date: Start date
        end_date: End date
        limit: Max rows (default 50)
        match_type: "equals" (exact) or "contains" (partial)
        search_type: "web", "image", "video"
    """
    response = _query(
        site_url=site_url,
        dimensions=["page"],
        start_date=start_date,
        end_date=end_date,
        row_limit=limit,
        search_type=search_type,
        filters={"dimension": "query", "operator": match_type, "expression": query_text},
    )
    return _format_rows(response, ["page"])


@mcp.tool()
def get_page_performance(
    site_url: str,
    page_url: str,
    start_date: str = "90daysAgo",
    end_date: str = "3daysAgo",
    search_type: str = "web",
) -> list[dict]:
    """Get daily performance trend for a specific page.

    Args:
        page_url: URL or URL part to filter by (uses contains matching)
        start_date: Start date (default 90 days for trend visibility)
        end_date: End date
        search_type: "web", "image", "video"
    """
    response = _query(
        site_url=site_url,
        dimensions=["date"],
        start_date=start_date,
        end_date=end_date,
        row_limit=25000,
        search_type=search_type,
        filters={"dimension": "page", "operator": "contains", "expression": page_url},
    )
    rows = _format_rows(response, ["date"])
    rows.sort(key=lambda x: x["date"])
    return rows


@mcp.tool()
def get_page_query_coverage(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    limit: int = 50,
    search_type: str = "web",
) -> list[dict]:
    """Get pages ranked by the number of unique queries they appear for.

    Helps identify content breadth — pages covering many queries are
    typically strong content hubs.

    Args:
        start_date: Start date
        end_date: End date
        limit: Max pages to return (default 50)
        search_type: "web", "image", "video"
    """
    response = _query(
        site_url=site_url,
        dimensions=["page", "query"],
        start_date=start_date,
        end_date=end_date,
        row_limit=25000,
        search_type=search_type,
    )
    page_queries: dict[str, dict] = {}
    for row in response.get("rows", []):
        page = row["keys"][0]
        if page not in page_queries:
            page_queries[page] = {
                "page": page,
                "query_count": 0,
                "total_clicks": 0,
                "total_impressions": 0,
            }
        page_queries[page]["query_count"] += 1
        page_queries[page]["total_clicks"] += row.get("clicks", 0)
        page_queries[page]["total_impressions"] += row.get("impressions", 0)

    results = sorted(page_queries.values(), key=lambda x: x["query_count"], reverse=True)
    return results[:limit]


# ═══════════════════════════════════════════════════════════════════════════════
# 5. COUNTRY, DEVICE & SEARCH APPEARANCE
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_performance_by_country(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    limit: int = 30,
    search_type: str = "web",
    filters=None,
) -> list[dict]:
    """Get search performance by country (ISO 3166-1 alpha-3 codes).

    Args:
        start_date: Start date
        end_date: End date
        limit: Max rows (default 30)
        search_type: "web", "image", "video", "news", "discover", "googleNews"
        filters: Optional filters
    """
    response = _query(
        site_url=site_url,
        dimensions=["country"],
        start_date=start_date,
        end_date=end_date,
        row_limit=limit,
        search_type=search_type,
        filters=filters,
    )
    return _format_rows(response, ["country"])


@mcp.tool()
def get_performance_by_device(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    search_type: str = "web",
    filters=None,
) -> list[dict]:
    """Get search performance by device type (DESKTOP, MOBILE, TABLET).

    Args:
        start_date: Start date
        end_date: End date
        search_type: "web", "image", "video", "news", "discover", "googleNews"
        filters: Optional filters
    """
    response = _query(
        site_url=site_url,
        dimensions=["device"],
        start_date=start_date,
        end_date=end_date,
        row_limit=10,
        search_type=search_type,
        filters=filters,
    )
    return _format_rows(response, ["device"])


@mcp.tool()
def get_performance_by_search_appearance(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    search_type: str = "web",
) -> list[dict]:
    """Get performance by search appearance type.

    Shows how different rich result types perform: AMP, rich results,
    FAQ snippets, video results, etc.

    Args:
        start_date: Start date
        end_date: End date
        search_type: "web", "image", "video"
    """
    response = _query(
        site_url=site_url,
        dimensions=["searchAppearance"],
        start_date=start_date,
        end_date=end_date,
        row_limit=100,
        search_type=search_type,
    )
    return _format_rows(response, ["searchAppearance"])


@mcp.tool()
def get_country_device_matrix(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    limit: int = 50,
    search_type: str = "web",
) -> list[dict]:
    """Get performance by country × device combination.

    Useful for identifying mobile vs desktop performance gaps per country.

    Args:
        start_date: Start date
        end_date: End date
        limit: Max rows (default 50)
        search_type: "web", "image", "video"
    """
    response = _query(
        site_url=site_url,
        dimensions=["country", "device"],
        start_date=start_date,
        end_date=end_date,
        row_limit=limit,
        search_type=search_type,
    )
    return _format_rows(response, ["country", "device"])


# ═══════════════════════════════════════════════════════════════════════════════
# 6. SEARCH TYPE SPECIFIC
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_discover_performance(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    limit: int = 50,
) -> list[dict]:
    """Get Google Discover performance by page.

    Note: Discover does NOT support the "query" dimension.

    Args:
        start_date: Start date
        end_date: End date
        limit: Max rows (default 50)
    """
    response = _query(
        site_url=site_url,
        dimensions=["page"],
        start_date=start_date,
        end_date=end_date,
        row_limit=limit,
        search_type="discover",
    )
    return _format_rows(response, ["page"])


@mcp.tool()
def get_discover_trend(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
) -> list[dict]:
    """Get daily Google Discover performance trend.

    Args:
        start_date: Start date
        end_date: End date
    """
    response = _query(
        site_url=site_url,
        dimensions=["date"],
        start_date=start_date,
        end_date=end_date,
        row_limit=25000,
        search_type="discover",
    )
    rows = _format_rows(response, ["date"])
    rows.sort(key=lambda x: x["date"])
    return rows


@mcp.tool()
def get_google_news_performance(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    limit: int = 50,
) -> list[dict]:
    """Get Google News performance by page.

    Args:
        start_date: Start date
        end_date: End date
        limit: Max rows (default 50)
    """
    response = _query(
        site_url=site_url,
        dimensions=["page"],
        start_date=start_date,
        end_date=end_date,
        row_limit=limit,
        search_type="googleNews",
    )
    return _format_rows(response, ["page"])


@mcp.tool()
def get_image_search_performance(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    limit: int = 50,
) -> list[dict]:
    """Get image search performance by query.

    Args:
        start_date: Start date
        end_date: End date
        limit: Max rows (default 50)
    """
    response = _query(
        site_url=site_url,
        dimensions=["query"],
        start_date=start_date,
        end_date=end_date,
        row_limit=limit,
        search_type="image",
    )
    return _format_rows(response, ["query"])


@mcp.tool()
def get_video_search_performance(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    limit: int = 50,
) -> list[dict]:
    """Get video search performance by query.

    Args:
        start_date: Start date
        end_date: End date
        limit: Max rows (default 50)
    """
    response = _query(
        site_url=site_url,
        dimensions=["query"],
        start_date=start_date,
        end_date=end_date,
        row_limit=limit,
        search_type="video",
    )
    return _format_rows(response, ["query"])


# ═══════════════════════════════════════════════════════════════════════════════
# 7. ADVANCED ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def get_query_page_matrix(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    limit: int = 1000,
    search_type: str = "web",
    filters=None,
) -> dict:
    """Get query × page matrix — essential for keyword cannibalization detection.

    Returns queries that rank with multiple pages, sorted by number of
    pages per query (most cannibalized first).

    Args:
        start_date: Start date
        end_date: End date
        limit: Max rows from API (default 1000)
        search_type: "web", "image", "video"
        filters: Optional filters
    """
    response = _query(
        site_url=site_url,
        dimensions=["query", "page"],
        start_date=start_date,
        end_date=end_date,
        row_limit=limit,
        search_type=search_type,
        filters=filters,
    )
    rows = _format_rows(response, ["query", "page"])

    query_pages: dict[str, list[dict]] = {}
    for row in rows:
        q = row["query"]
        if q not in query_pages:
            query_pages[q] = []
        query_pages[q].append({
            "page": row["page"],
            "clicks": row["clicks"],
            "impressions": row["impressions"],
            "ctr": row["ctr"],
            "position": row["position"],
        })

    cannibalized = []
    for query, pages in query_pages.items():
        if len(pages) > 1:
            pages.sort(key=lambda x: x["clicks"], reverse=True)
            cannibalized.append({
                "query": query,
                "page_count": len(pages),
                "total_clicks": sum(p["clicks"] for p in pages),
                "pages": pages,
            })
    cannibalized.sort(key=lambda x: x["page_count"], reverse=True)

    return {
        "cannibalized_queries": cannibalized[:100],
        "total_cannibalized": len(cannibalized),
        "total_unique_queries": len(query_pages),
    }


@mcp.tool()
def get_position_distribution(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    search_type: str = "web",
    filters=None,
) -> dict:
    """Get position distribution — how many queries rank in each position bucket.

    Buckets: 1-3 (top), 4-10 (page 1), 11-20 (page 2), 21-50, 51-100, 100+

    Args:
        start_date: Start date
        end_date: End date
        search_type: "web", "image", "video"
        filters: Optional filters
    """
    response = _query(
        site_url=site_url,
        dimensions=["query"],
        start_date=start_date,
        end_date=end_date,
        row_limit=25000,
        search_type=search_type,
        filters=filters,
    )
    rows = _format_rows(response, ["query"])

    buckets = {
        "1-3 (top)": {"count": 0, "clicks": 0, "impressions": 0},
        "4-10 (page 1)": {"count": 0, "clicks": 0, "impressions": 0},
        "11-20 (page 2)": {"count": 0, "clicks": 0, "impressions": 0},
        "21-50": {"count": 0, "clicks": 0, "impressions": 0},
        "51-100": {"count": 0, "clicks": 0, "impressions": 0},
        "100+": {"count": 0, "clicks": 0, "impressions": 0},
    }

    for row in rows:
        pos = row["position"]
        if pos <= 3:
            bucket = "1-3 (top)"
        elif pos <= 10:
            bucket = "4-10 (page 1)"
        elif pos <= 20:
            bucket = "11-20 (page 2)"
        elif pos <= 50:
            bucket = "21-50"
        elif pos <= 100:
            bucket = "51-100"
        else:
            bucket = "100+"
        buckets[bucket]["count"] += 1
        buckets[bucket]["clicks"] += row["clicks"]
        buckets[bucket]["impressions"] += row["impressions"]

    return {
        "distribution": buckets,
        "total_queries": len(rows),
    }


@mcp.tool()
def get_ctr_by_position(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    search_type: str = "web",
) -> list[dict]:
    """Analyze actual CTR vs position — compare your CTR against expected rates.

    Shows average CTR for each position range, helping identify pages
    that outperform or underperform their ranking position.

    Args:
        start_date: Start date
        end_date: End date
        search_type: "web", "image", "video"
    """
    response = _query(
        site_url=site_url,
        dimensions=["query"],
        start_date=start_date,
        end_date=end_date,
        row_limit=25000,
        search_type=search_type,
    )
    rows = _format_rows(response, ["query"])

    position_groups: dict[str, dict] = {}
    for row in rows:
        pos = row["position"]
        if pos <= 1:
            group = "Position 1"
        elif pos <= 2:
            group = "Position 2"
        elif pos <= 3:
            group = "Position 3"
        elif pos <= 5:
            group = "Position 4-5"
        elif pos <= 10:
            group = "Position 6-10"
        elif pos <= 20:
            group = "Position 11-20"
        elif pos <= 50:
            group = "Position 21-50"
        else:
            group = "Position 50+"

        if group not in position_groups:
            position_groups[group] = {
                "position_range": group,
                "query_count": 0,
                "total_clicks": 0,
                "total_impressions": 0,
            }
        position_groups[group]["query_count"] += 1
        position_groups[group]["total_clicks"] += row["clicks"]
        position_groups[group]["total_impressions"] += row["impressions"]

    results = []
    for group in position_groups.values():
        group["average_ctr"] = round(
            group["total_clicks"] / group["total_impressions"], 4
        ) if group["total_impressions"] else 0
        results.append(group)

    order = [
        "Position 1", "Position 2", "Position 3", "Position 4-5",
        "Position 6-10", "Position 11-20", "Position 21-50", "Position 50+",
    ]
    results.sort(key=lambda x: order.index(x["position_range"]) if x["position_range"] in order else 99)
    return results


@mcp.tool()
def get_top_growing_queries(
    site_url: str,
    days: int = 28,
    limit: int = 50,
    min_impressions: int = 10,
    search_type: str = "web",
) -> list[dict]:
    """Find queries with the biggest growth comparing current period vs previous period.

    Compares last N days against the previous N days.

    Args:
        days: Period length in days (default 28)
        limit: Max results (default 50)
        min_impressions: Minimum impressions in either period (default 10)
        search_type: "web", "image", "video"
    """
    p2_end = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    p2_start = (datetime.now() - timedelta(days=3 + days - 1)).strftime("%Y-%m-%d")
    p1_end = (datetime.now() - timedelta(days=3 + days)).strftime("%Y-%m-%d")
    p1_start = (datetime.now() - timedelta(days=3 + 2 * days - 1)).strftime("%Y-%m-%d")

    r1 = _query(site_url=site_url, dimensions=["query"], start_date=p1_start, end_date=p1_end,
                 row_limit=10000, search_type=search_type)
    r2 = _query(site_url=site_url, dimensions=["query"], start_date=p2_start, end_date=p2_end,
                 row_limit=10000, search_type=search_type)

    p1_data = {r["keys"][0]: r for r in r1.get("rows", [])}
    p2_data = {r["keys"][0]: r for r in r2.get("rows", [])}

    results = []
    for query in set(p1_data.keys()) | set(p2_data.keys()):
        old = p1_data.get(query, {})
        new = p2_data.get(query, {})
        old_clicks = old.get("clicks", 0)
        new_clicks = new.get("clicks", 0)
        old_imp = old.get("impressions", 0)
        new_imp = new.get("impressions", 0)

        if old_imp < min_impressions and new_imp < min_impressions:
            continue

        clicks_change = new_clicks - old_clicks
        if clicks_change <= 0:
            continue

        results.append({
            "query": query,
            "period1_clicks": old_clicks,
            "period2_clicks": new_clicks,
            "clicks_change": clicks_change,
            "period1_impressions": old_imp,
            "period2_impressions": new_imp,
            "impressions_change": new_imp - old_imp,
            "period1_position": round(old.get("position", 0), 2),
            "period2_position": round(new.get("position", 0), 2),
        })

    results.sort(key=lambda x: x["clicks_change"], reverse=True)
    return results[:limit]


@mcp.tool()
def get_top_declining_queries(
    site_url: str,
    days: int = 28,
    limit: int = 50,
    min_impressions: int = 10,
    search_type: str = "web",
) -> list[dict]:
    """Find queries with the biggest decline comparing current period vs previous period.

    Compares last N days against the previous N days.

    Args:
        days: Period length in days (default 28)
        limit: Max results (default 50)
        min_impressions: Minimum impressions in either period (default 10)
        search_type: "web", "image", "video"
    """
    p2_end = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    p2_start = (datetime.now() - timedelta(days=3 + days - 1)).strftime("%Y-%m-%d")
    p1_end = (datetime.now() - timedelta(days=3 + days)).strftime("%Y-%m-%d")
    p1_start = (datetime.now() - timedelta(days=3 + 2 * days - 1)).strftime("%Y-%m-%d")

    r1 = _query(site_url=site_url, dimensions=["query"], start_date=p1_start, end_date=p1_end,
                 row_limit=10000, search_type=search_type)
    r2 = _query(site_url=site_url, dimensions=["query"], start_date=p2_start, end_date=p2_end,
                 row_limit=10000, search_type=search_type)

    p1_data = {r["keys"][0]: r for r in r1.get("rows", [])}
    p2_data = {r["keys"][0]: r for r in r2.get("rows", [])}

    results = []
    for query in set(p1_data.keys()) | set(p2_data.keys()):
        old = p1_data.get(query, {})
        new = p2_data.get(query, {})
        old_clicks = old.get("clicks", 0)
        new_clicks = new.get("clicks", 0)
        old_imp = old.get("impressions", 0)
        new_imp = new.get("impressions", 0)

        if old_imp < min_impressions and new_imp < min_impressions:
            continue

        clicks_change = new_clicks - old_clicks
        if clicks_change >= 0:
            continue

        results.append({
            "query": query,
            "period1_clicks": old_clicks,
            "period2_clicks": new_clicks,
            "clicks_change": clicks_change,
            "period1_impressions": old_imp,
            "period2_impressions": new_imp,
            "impressions_change": new_imp - old_imp,
            "period1_position": round(old.get("position", 0), 2),
            "period2_position": round(new.get("position", 0), 2),
        })

    results.sort(key=lambda x: x["clicks_change"])
    return results[:limit]


@mcp.tool()
def get_new_queries(
    site_url: str,
    days: int = 28,
    limit: int = 50,
    min_clicks: int = 1,
    search_type: str = "web",
) -> list[dict]:
    """Find new queries that appeared in the current period but NOT in the previous period.

    Args:
        days: Period length in days (default 28)
        limit: Max results (default 50)
        min_clicks: Minimum clicks in current period (default 1)
        search_type: "web", "image", "video"
    """
    p2_end = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    p2_start = (datetime.now() - timedelta(days=3 + days - 1)).strftime("%Y-%m-%d")
    p1_end = (datetime.now() - timedelta(days=3 + days)).strftime("%Y-%m-%d")
    p1_start = (datetime.now() - timedelta(days=3 + 2 * days - 1)).strftime("%Y-%m-%d")

    r1 = _query(site_url=site_url, dimensions=["query"], start_date=p1_start, end_date=p1_end,
                 row_limit=25000, search_type=search_type)
    r2 = _query(site_url=site_url, dimensions=["query"], start_date=p2_start, end_date=p2_end,
                 row_limit=25000, search_type=search_type)

    old_queries = {r["keys"][0] for r in r1.get("rows", [])}
    results = []
    for row in r2.get("rows", []):
        q = row["keys"][0]
        if q not in old_queries and row.get("clicks", 0) >= min_clicks:
            results.append({
                "query": q,
                "clicks": row.get("clicks", 0),
                "impressions": row.get("impressions", 0),
                "ctr": round(row.get("ctr", 0), 4),
                "position": round(row.get("position", 0), 2),
            })

    results.sort(key=lambda x: x["clicks"], reverse=True)
    return results[:limit]


@mcp.tool()
def get_lost_queries(
    site_url: str,
    days: int = 28,
    limit: int = 50,
    min_clicks: int = 1,
    search_type: str = "web",
) -> list[dict]:
    """Find queries that appeared in the previous period but NOT in the current period.

    Args:
        days: Period length in days (default 28)
        limit: Max results (default 50)
        min_clicks: Minimum clicks in previous period (default 1)
        search_type: "web", "image", "video"
    """
    p2_end = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    p2_start = (datetime.now() - timedelta(days=3 + days - 1)).strftime("%Y-%m-%d")
    p1_end = (datetime.now() - timedelta(days=3 + days)).strftime("%Y-%m-%d")
    p1_start = (datetime.now() - timedelta(days=3 + 2 * days - 1)).strftime("%Y-%m-%d")

    r1 = _query(site_url=site_url, dimensions=["query"], start_date=p1_start, end_date=p1_end,
                 row_limit=25000, search_type=search_type)
    r2 = _query(site_url=site_url, dimensions=["query"], start_date=p2_start, end_date=p2_end,
                 row_limit=25000, search_type=search_type)

    new_queries = {r["keys"][0] for r in r2.get("rows", [])}
    results = []
    for row in r1.get("rows", []):
        q = row["keys"][0]
        if q not in new_queries and row.get("clicks", 0) >= min_clicks:
            results.append({
                "query": q,
                "clicks": row.get("clicks", 0),
                "impressions": row.get("impressions", 0),
                "ctr": round(row.get("ctr", 0), 4),
                "position": round(row.get("position", 0), 2),
            })

    results.sort(key=lambda x: x["clicks"], reverse=True)
    return results[:limit]


# ═══════════════════════════════════════════════════════════════════════════════
# 8. URL INSPECTION
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def inspect_url(site_url: str, url: str) -> dict:
    """Inspect a URL's indexing status, crawl info, and mobile usability.

    Returns: coverage state, indexing state, crawl time, robots status,
    canonical URL, mobile usability, rich results info.

    Args:
        url: Full URL to inspect (e.g. "https://aihomedesign.com/page")
    """
    result = _service().urlInspection().index().inspect(
        body={"inspectionUrl": url, "siteUrl": site_url}
    ).execute()

    inspection = result.get("inspectionResult", {})
    index_status = inspection.get("indexStatusResult", {})
    mobile = inspection.get("mobileUsabilityResult", {})
    rich_results = inspection.get("richResultsResult", {})

    return {
        "url": url,
        "index_status": {
            "verdict": index_status.get("verdict"),
            "coverage_state": index_status.get("coverageState"),
            "robotsTxtState": index_status.get("robotsTxtState"),
            "indexing_state": index_status.get("indexingState"),
            "last_crawl_time": index_status.get("lastCrawlTime"),
            "page_fetch_state": index_status.get("pageFetchState"),
            "google_canonical": index_status.get("googleCanonical"),
            "user_canonical": index_status.get("userCanonical"),
            "crawled_as": index_status.get("crawledAs"),
            "referring_urls": index_status.get("referringUrls", []),
            "sitemap": index_status.get("sitemap", []),
        },
        "mobile_usability": {
            "verdict": mobile.get("verdict"),
            "issues": mobile.get("issues", []),
        },
        "rich_results": {
            "verdict": rich_results.get("verdict"),
            "detected_items": rich_results.get("detectedItems", []),
        },
    }


@mcp.tool()
def batch_inspect_urls(site_url: str, urls: list[str]) -> list[dict]:
    """Inspect multiple URLs for indexing status (one API call per URL).

    Note: Each URL is inspected individually. Rate limits may apply for large batches.
    Recommended max: 50 URLs per batch.

    Args:
        urls: List of full URLs to inspect
    """
    svc = _service()
    results = []
    for url in urls[:50]:
        try:
            result = svc.urlInspection().index().inspect(
                body={"inspectionUrl": url, "siteUrl": site_url}
            ).execute()
            inspection = result.get("inspectionResult", {})
            idx = inspection.get("indexStatusResult", {})
            results.append({
                "url": url,
                "verdict": idx.get("verdict"),
                "coverage_state": idx.get("coverageState"),
                "indexing_state": idx.get("indexingState"),
                "last_crawl_time": idx.get("lastCrawlTime"),
                "page_fetch_state": idx.get("pageFetchState"),
                "google_canonical": idx.get("googleCanonical"),
                "crawled_as": idx.get("crawledAs"),
            })
        except Exception as e:
            results.append({"url": url, "error": str(e)})
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 9. SITEMAPS
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def list_sitemaps(site_url: str) -> list[dict]:
    """List all sitemaps submitted for this site.

    Returns: sitemap path, type, last submitted, last downloaded,
    isPending, isSitemapsIndex, warnings, errors, content counts.
    """
    response = _service().sitemaps().list(siteUrl=site_url).execute()
    sitemaps = []
    for sm in response.get("sitemap", []):
        sitemaps.append({
            "path": sm.get("path"),
            "type": sm.get("type"),
            "last_submitted": sm.get("lastSubmitted"),
            "last_downloaded": sm.get("lastDownloaded"),
            "is_pending": sm.get("isPending"),
            "is_sitemaps_index": sm.get("isSitemapsIndex"),
            "warnings": sm.get("warnings"),
            "errors": sm.get("errors"),
            "contents": sm.get("contents", []),
        })
    return sitemaps


@mcp.tool()
def get_sitemap(site_url: str, sitemap_url: str) -> dict:
    """Get detailed info for a specific sitemap.

    Args:
        sitemap_url: Full URL of the sitemap (e.g. "https://aihomedesign.com/sitemap.xml")
    """
    sm = _service().sitemaps().get(siteUrl=site_url, feedpath=sitemap_url).execute()
    return {
        "path": sm.get("path"),
        "type": sm.get("type"),
        "last_submitted": sm.get("lastSubmitted"),
        "last_downloaded": sm.get("lastDownloaded"),
        "is_pending": sm.get("isPending"),
        "is_sitemaps_index": sm.get("isSitemapsIndex"),
        "warnings": sm.get("warnings"),
        "errors": sm.get("errors"),
        "contents": sm.get("contents", []),
    }


@mcp.tool()
def submit_sitemap(site_url: str, sitemap_url: str) -> dict:
    """Submit a sitemap to Google Search Console.

    Args:
        sitemap_url: Full URL of the sitemap (e.g. "https://aihomedesign.com/sitemap.xml")
    """
    _service().sitemaps().submit(siteUrl=site_url, feedpath=sitemap_url).execute()
    return {"status": "submitted", "sitemap_url": sitemap_url}


@mcp.tool()
def delete_sitemap(site_url: str, sitemap_url: str) -> dict:
    """Delete a sitemap from Google Search Console.

    Args:
        sitemap_url: Full URL of the sitemap to delete
    """
    _service().sitemaps().delete(siteUrl=site_url, feedpath=sitemap_url).execute()
    return {"status": "deleted", "sitemap_url": sitemap_url}


# ═══════════════════════════════════════════════════════════════════════════════
# 10. SITES
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def list_sites() -> list[dict]:
    """List all sites the service account has access to in Search Console.

    Returns site URL and permission level for each site.
    """
    response = _service().sites().list().execute()
    sites = []
    for site in response.get("siteEntry", []):
        sites.append({
            "site_url": site.get("siteUrl"),
            "permission_level": site.get("permissionLevel"),
        })
    return sites


@mcp.tool()
def get_site(site_url: str) -> dict:
    """Get details for the currently configured site.

    Returns the site URL and permission level.
    """
    site = _service().sites().get(siteUrl=site_url).execute()
    return {
        "site_url": site.get("siteUrl"),
        "permission_level": site.get("permissionLevel"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 11. SEO ANALYSIS WORKFLOWS
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def content_opportunities(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    min_impressions: int = 100,
    max_ctr: float = 0.05,
    min_position: float = 5.0,
    max_position: float = 20.0,
    limit: int = 30,
    search_type: str = "web",
) -> dict:
    """Find content optimization opportunities — pages with high impressions
    but low CTR at positions 5-20.

    Each result includes an opportunity_score calculated as:
        impressions * (expected_ctr - actual_ctr)
    where expected_ctr is 0.05 (5%).

    Higher score = bigger potential traffic gain from optimization.

    Args:
        start_date: Start date
        end_date: End date
        min_impressions: Minimum impressions (default 100)
        max_ctr: Maximum CTR threshold (default 0.05 = 5%)
        min_position: Minimum average position (default 5.0)
        max_position: Maximum average position (default 20.0)
        limit: Max results (default 30)
        search_type: "web", "image", "video"
    """
    response = _query(
        site_url=site_url,
        dimensions=["page", "query"],
        start_date=start_date,
        end_date=end_date,
        row_limit=5000,
        search_type=search_type,
    )
    rows = _format_rows(response, ["page", "query"])

    # Aggregate by page
    page_data: dict[str, dict] = {}
    for row in rows:
        page = row["page"]
        if page not in page_data:
            page_data[page] = {
                "page": page,
                "queries": [],
                "total_clicks": 0,
                "total_impressions": 0,
            }
        page_data[page]["queries"].append(row["query"])
        page_data[page]["total_clicks"] += row["clicks"]
        page_data[page]["total_impressions"] += row["impressions"]

    opportunities = []
    for page, data in page_data.items():
        impr = data["total_impressions"]
        clicks = data["total_clicks"]
        ctr = clicks / impr if impr > 0 else 0

        # Get average position for this page
        page_rows = [r for r in rows if r["page"] == page]
        avg_pos = sum(r["position"] * r["impressions"] for r in page_rows) / impr if impr > 0 else 0

        if (impr >= min_impressions and ctr <= max_ctr
                and min_position <= avg_pos <= max_position):
            expected_ctr = 0.05
            score = impr * max(expected_ctr - ctr, 0)
            opportunities.append({
                "page": page,
                "clicks": clicks,
                "impressions": impr,
                "ctr": round(ctr, 4),
                "avg_position": round(avg_pos, 2),
                "opportunity_score": round(score, 1),
                "top_queries": data["queries"][:5],
                "query_count": len(data["queries"]),
            })

    opportunities.sort(key=lambda x: x["opportunity_score"], reverse=True)
    return {
        "opportunities": opportunities[:limit],
        "total_found": len(opportunities),
    }


@mcp.tool()
def seo_performance_report(
    site_url: str,
    days: int = 28,
    search_type: str = "web",
) -> dict:
    """Generate a comprehensive SEO performance report comparing two periods.

    Includes:
    - Overall metrics (clicks, impressions, CTR, position) for current vs previous period
    - Percentage changes
    - Top 10 queries by clicks
    - Top 5 growing queries
    - Top 5 declining queries
    - Top 10 pages by clicks

    Args:
        days: Number of days for the report period (default 28)
        search_type: "web", "image", "video"
    """
    today = datetime.now()
    current_end = (today - timedelta(days=3)).strftime("%Y-%m-%d")
    current_start = (today - timedelta(days=3 + days)).strftime("%Y-%m-%d")
    prev_end = (today - timedelta(days=3 + days + 1)).strftime("%Y-%m-%d")
    prev_start = (today - timedelta(days=3 + 2 * days + 1)).strftime("%Y-%m-%d")

    # Current period totals
    current_resp = _query(
        site_url=site_url, start_date=current_start, end_date=current_end,
        search_type=search_type,
    )
    prev_resp = _query(
        site_url=site_url, start_date=prev_start, end_date=prev_end,
        search_type=search_type,
    )

    def _totals(resp):
        rows = resp.get("rows", [])
        if not rows:
            return {"clicks": 0, "impressions": 0, "ctr": 0, "position": 0}
        r = rows[0]
        return {
            "clicks": r.get("clicks", 0),
            "impressions": r.get("impressions", 0),
            "ctr": round(r.get("ctr", 0), 4),
            "position": round(r.get("position", 0), 2),
        }

    cur = _totals(current_resp)
    prev = _totals(prev_resp)

    def _pct(cur_val, prev_val):
        if prev_val == 0:
            return None
        return round((cur_val - prev_val) / prev_val * 100, 1)

    # Top queries
    top_q_resp = _query(
        site_url=site_url, dimensions=["query"],
        start_date=current_start, end_date=current_end,
        row_limit=1000, search_type=search_type,
    )
    top_queries = _format_rows(top_q_resp, ["query"])
    top_queries.sort(key=lambda x: x["clicks"], reverse=True)

    # Top pages
    top_p_resp = _query(
        site_url=site_url, dimensions=["page"],
        start_date=current_start, end_date=current_end,
        row_limit=100, search_type=search_type,
    )
    top_pages = _format_rows(top_p_resp, ["page"])
    top_pages.sort(key=lambda x: x["clicks"], reverse=True)

    # Growing and declining queries (compare periods)
    prev_q_resp = _query(
        site_url=site_url, dimensions=["query"],
        start_date=prev_start, end_date=prev_end,
        row_limit=1000, search_type=search_type,
    )
    prev_queries = {r["query"]: r for r in _format_rows(prev_q_resp, ["query"])}

    changes = []
    for q in top_queries:
        pq = prev_queries.get(q["query"])
        if pq:
            diff = q["clicks"] - pq["clicks"]
            changes.append({**q, "click_change": diff, "prev_clicks": pq["clicks"]})

    growing = sorted([c for c in changes if c["click_change"] > 0],
                     key=lambda x: x["click_change"], reverse=True)
    declining = sorted([c for c in changes if c["click_change"] < 0],
                       key=lambda x: x["click_change"])

    return {
        "period": {"start": current_start, "end": current_end, "days": days},
        "previous_period": {"start": prev_start, "end": prev_end},
        "current": cur,
        "previous": prev,
        "changes": {
            "clicks_pct": _pct(cur["clicks"], prev["clicks"]),
            "impressions_pct": _pct(cur["impressions"], prev["impressions"]),
            "ctr_pct": _pct(cur["ctr"], prev["ctr"]),
            "position_change": round(cur["position"] - prev["position"], 2),
        },
        "top_queries": top_queries[:10],
        "top_pages": top_pages[:10],
        "growing_queries": growing[:5],
        "declining_queries": declining[:5],
    }


@mcp.tool()
def indexing_audit(
    site_url: str,
    start_date: str = "28daysAgo",
    end_date: str = "3daysAgo",
    top_n: int = 20,
    search_type: str = "web",
) -> dict:
    """Audit indexing status for your top pages by impressions.

    Fetches your most visible pages, then inspects each for indexing issues.
    Results are categorized by verdict: Indexed, Not Indexed, Partial, etc.

    Args:
        start_date: Start date for finding top pages
        end_date: End date for finding top pages
        top_n: Number of top pages to audit (default 20, max 50)
        search_type: "web", "image", "video"
    """
    top_n = min(top_n, 50)

    # Get top pages by impressions
    page_resp = _query(
        site_url=site_url, dimensions=["page"],
        start_date=start_date, end_date=end_date,
        row_limit=top_n, search_type=search_type,
    )
    pages = _format_rows(page_resp, ["page"])
    pages.sort(key=lambda x: x["impressions"], reverse=True)

    # Inspect each page
    svc = _service()
    results = []
    issues = []

    for page_row in pages[:top_n]:
        url = page_row["page"]
        try:
            inspection = svc.urlInspection().index().inspect(body={
                "inspectionUrl": url,
                "siteUrl": site_url,
            }).execute()
            result = inspection.get("inspectionResult", {})
            index_status = result.get("indexStatusResult", {})
            verdict = index_status.get("verdict", "UNKNOWN")
            coverage = index_status.get("coverageState", "")
            crawled = index_status.get("lastCrawlTime", "")
            robot_blocked = index_status.get("robotsTxtState", "")

            entry = {
                "url": url,
                "impressions": page_row["impressions"],
                "clicks": page_row["clicks"],
                "verdict": verdict,
                "coverage_state": coverage,
                "last_crawled": crawled,
                "robots_blocked": robot_blocked == "DISALLOWED",
            }
            results.append(entry)

            if verdict != "PASS":
                issues.append(entry)

        except Exception as e:
            results.append({
                "url": url,
                "impressions": page_row["impressions"],
                "clicks": page_row["clicks"],
                "verdict": "ERROR",
                "error": str(e),
            })
            issues.append(results[-1])

    # Categorize
    verdicts: dict[str, int] = {}
    for r in results:
        v = r["verdict"]
        verdicts[v] = verdicts.get(v, 0) + 1

    return {
        "total_audited": len(results),
        "verdict_summary": verdicts,
        "issues_found": len(issues),
        "issues": issues,
        "all_results": results,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    mcp.run()
