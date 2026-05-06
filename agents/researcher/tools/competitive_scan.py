"""Competitive intelligence scan tool.

Structured task tool — guides the agent through researching competitors
via web search and comparing findings against the known landscape.
"""

from strands import tool


@tool
def competitive_scan(
    competitors: str = "",
    focus_areas: str = "",
    depth: str = "standard",
) -> str:
    """Run a competitive intelligence scan using web search.

    The agent should use this tool when asked to research competitors,
    monitor the market, or update competitive positioning.

    Args:
        competitors: Comma-separated list of competitor names or URLs.
            Empty means use known competitors from memory.
        focus_areas: Comma-separated areas to investigate (e.g.
            'pricing,new features,partnerships'). Empty means full scan.
        depth: 'quick' (headlines only), 'standard' (feature comparison),
            or 'deep' (full analysis with positioning recommendations).

    Returns:
        Instructions for the agent to follow when running a competitive scan.
    """
    competitor_step = ""
    if competitors:
        competitor_step = f"1. Research these competitors: {competitors}\n"
    else:
        competitor_step = (
            "1. Recall known competitors from memory. If no competitors in\n"
            "   memory, ask the user to specify which competitors to track.\n"
        )

    focus_filter = ""
    if focus_areas:
        focus_filter = f"\nFocus areas: {focus_areas}. Skip other areas.\n"

    depth_guidance = {
        "quick": (
            "Quick scan: headlines and major announcements only.\n"
            "One paragraph per competitor, bullet-point format."
        ),
        "standard": (
            "Standard scan: feature comparison and notable changes.\n"
            "Include feature matrix, pricing changes, and strategic moves."
        ),
        "deep": (
            "Deep analysis: full competitive positioning review.\n"
            "Include feature matrix, pricing analysis, SWOT per competitor,\n"
            "white space opportunities, and strategic recommendations."
        ),
    }

    return (
        f"Run a competitive intelligence scan.\n"
        f"Depth: {depth}\n"
        f"{focus_filter}\n"
        f"{depth_guidance.get(depth, depth_guidance['standard'])}\n\n"
        f"Steps:\n"
        f"{competitor_step}"
        "2. For each competitor, call the `web_search` tool to find:\n"
        "   - Recent product announcements and feature launches\n"
        "   - Pricing changes\n"
        "   - Partnerships and integrations\n"
        "   - Hiring signals (job postings indicating strategy)\n"
        "   - User reviews and sentiment\n"
        "3. Compare findings against the competitive landscape in memory.\n"
        "   Identify what CHANGED since the last scan.\n"
        "4. Update memory with the latest competitive data.\n"
        "5. Identify opportunities (gaps competitors haven't filled) and\n"
        "   threats (areas where competitors are advancing).\n"
        "6. Post the competitive brief as an Asana comment.\n"
        "7. Flag confidence level for each finding (confirmed / reported / rumored)."
    )
