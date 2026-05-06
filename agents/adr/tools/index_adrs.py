"""Index the repo's ADR directory into a structured catalog.

The agent calls this once per invocation before matching. Parses each ADR
markdown file into {number, title, status, supersedes, superseded_by,
body, path}. Later tools consume this structure for matching.

ADR format assumed (lenient):
- Filename like `0001-use-postgres.md` or `0001_use_postgres.md` — number
  is the leading numeric segment
- First `# ` heading is the title (strip any `ADR-NNNN:` prefix)
- `## Status` section's first non-empty line is the status; normalized to
  proposed / accepted / deprecated / superseded
- `## Superseded by ADR-NNNN` or similar is parsed if present
- Missing status defaults to `accepted`
"""

import re

from strands import tool


_STATUS_CANON = {
    "proposed": "proposed",
    "accepted": "accepted",
    "approved": "accepted",
    "deprecated": "deprecated",
    "superseded": "superseded",
    "rejected": "deprecated",
}


def _parse_number(filename: str, content: str) -> int | None:
    """Extract the ADR number from filename first, then first-line heading."""
    m = re.match(r"^0*(\d+)[-_]", filename)
    if m:
        return int(m.group(1))
    m = re.search(r"^#\s*ADR[- ]?0*(\d+)", content, re.MULTILINE | re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _parse_title(content: str) -> str:
    """First `# ` heading, stripping any `ADR-NNNN:` prefix."""
    m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if not m:
        return "(untitled)"
    title = m.group(1).strip()
    title = re.sub(r"^ADR[- ]?\d+[:\s-]+", "", title, flags=re.IGNORECASE).strip()
    return title


def _parse_status(content: str) -> str:
    """First non-empty line under `## Status`; default `accepted`."""
    # Grab everything from `## Status` to the next `## ` heading
    m = re.search(r"^##\s+Status\s*\n(.+?)(?=^##\s|\Z)",
                  content, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    if not m:
        return "accepted"
    lines = [line.strip() for line in m.group(1).strip().splitlines() if line.strip()]
    if not lines:
        return "accepted"
    first = lines[0].lower()
    for key, canon in _STATUS_CANON.items():
        if key in first:
            return canon
    return "accepted"


def _parse_superseded_by(content: str) -> int | None:
    m = re.search(r"superseded\s+by\s+ADR[- ]?0*(\d+)", content, re.IGNORECASE)
    return int(m.group(1)) if m else None


@tool
def index_adrs(files: list[dict]) -> list[dict]:
    """Parse a list of ADR markdown files into a structured index.

    The agent obtains `files` by calling the GitHub MCP server to list
    and read the files in the ADR directory — each `file` in the list
    is a dict with at least `path` and `content` keys.

    Args:
        files: List of {path: str, content: str} dicts, one per ADR.

    Returns:
        List of parsed ADR records:
            {
              "number": int | None,
              "title": str,
              "status": str,  # proposed | accepted | deprecated | superseded
              "supersedes": int | None,
              "superseded_by": int | None,
              "path": str,
              "body": str,  # full markdown body for matching
            }
        Sorted by number ascending, with unnumbered ADRs last.
    """
    parsed = []
    for f in files:
        path = f.get("path", "")
        content = f.get("content", "") or ""
        filename = path.rsplit("/", 1)[-1]

        # Skip non-ADR files a loose filter might have picked up
        if not filename.lower().endswith((".md", ".markdown")):
            continue
        if filename.lower() in ("readme.md", "index.md", "template.md", "0000-template.md"):
            continue

        parsed.append({
            "number": _parse_number(filename, content),
            "title": _parse_title(content),
            "status": _parse_status(content),
            "superseded_by": _parse_superseded_by(content),
            "supersedes": None,  # set in second pass
            "path": path,
            "body": content,
        })

    # Cross-link supersedes
    by_number = {a["number"]: a for a in parsed if a["number"] is not None}
    for a in parsed:
        sb = a["superseded_by"]
        if sb and sb in by_number:
            by_number[sb]["supersedes"] = a["number"]

    parsed.sort(key=lambda a: (a["number"] is None, a["number"] or 0))
    return parsed
