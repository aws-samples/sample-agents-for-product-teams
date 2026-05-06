"""Match GitHub issues and PRs against an ADR index.

Two signals combined:

1. Keyword overlap — cheap, catches explicit references and obvious term
   matches. Tokenized on lowercase alphanumeric; stopword-filtered.
2. Semantic similarity — Bedrock Titan embeddings, cosine similarity on
   the issue/PR body vs. each ADR body. Catches paraphrased scenarios.

Combined score = 0.4 * keyword_score + 0.6 * semantic_score. Tunable later.

These tools return ranked results with rationales. The agent decides
whether to apply labels and what to post.
"""

import logging
import math
import re

import boto3
from strands import tool

logger = logging.getLogger(__name__)

_STOPWORDS = frozenset("""
a an the and or but if then else for to of in on at by with from as is are was
were be been being have has had do does did will would should could may might
must can this that these those it its their our your my we you they he she
not no yes i me us them him her about into out over under up down what which
who whom whose when where why how all any some each other more most less many
much few own same so than too very s t just don now also one two three
""".split())

_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


def _tokenize(text: str) -> set[str]:
    tokens = _TOKEN_RE.findall((text or "").lower())
    return {t for t in tokens if t not in _STOPWORDS}


def _keyword_score(query_tokens: set[str], adr: dict) -> float:
    """Jaccard-weighted overlap between query tokens and ADR tokens.

    Weights title tokens ~3x body tokens since titles are the most
    semantically dense part of an ADR.
    """
    if not query_tokens:
        return 0.0
    title_tokens = _tokenize(adr["title"])
    body_tokens = _tokenize(adr["body"])
    all_adr_tokens = title_tokens | body_tokens
    if not all_adr_tokens:
        return 0.0

    title_overlap = len(query_tokens & title_tokens)
    body_overlap = len(query_tokens & body_tokens)

    # Normalize so scores fit in [0, 1]
    weighted = (3 * title_overlap + body_overlap) / (3 * len(title_tokens) + len(body_tokens) + 1)
    return min(weighted * 2.0, 1.0)  # scale up and clamp


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


_bedrock = None


def _embed(text: str, model_id: str = "amazon.titan-embed-text-v2:0") -> list[float]:
    """Fetch a single embedding from Bedrock. Truncates input to the
    model's limit (8K tokens ≈ 32K chars)."""
    global _bedrock
    if _bedrock is None:
        _bedrock = boto3.client("bedrock-runtime")

    text = (text or "")[:30000]
    if not text.strip():
        return []

    import json
    resp = _bedrock.invoke_model(
        modelId=model_id,
        body=json.dumps({"inputText": text}),
    )
    return json.loads(resp["body"].read())["embedding"]


def _build_rationale(adr: dict, query: str, query_tokens: set[str]) -> str:
    """Human-readable one-liner: why this ADR applies."""
    title_hits = _tokenize(adr["title"]) & query_tokens
    if title_hits:
        hit_list = ", ".join(sorted(title_hits)[:3])
        return (f"The issue/PR references terms ({hit_list}) that appear in "
                f"this ADR's title. Verify whether the ADR's guidance constrains "
                f"the proposed work.")
    return ("Semantic similarity between the issue/PR content and the ADR body "
            "suggests the ADR's scope applies. Verify against the ADR's "
            "Decision section.")


@tool
def match_issue_to_adrs(
    issue_text: str,
    adr_index: list[dict],
    confidence_threshold: float = 0.65,
    require_status: str = "accepted",
) -> list[dict]:
    """Score each ADR against an issue; return matches above threshold.

    Args:
        issue_text: Issue title + body + comments concatenated.
        adr_index: Output of `index_adrs`.
        confidence_threshold: Matches below this are dropped.
        require_status: Only consider ADRs with this status; "any" for all.

    Returns:
        List of matches, each:
            {
              "adr": <adr dict from index>,
              "score": float,
              "keyword_score": float,
              "semantic_score": float,
              "rationale": str,
            }
        Sorted by score descending.
    """
    if not adr_index:
        return []

    query_tokens = _tokenize(issue_text)

    # Embed the query once; embed each eligible ADR
    eligible = [
        a for a in adr_index
        if (require_status == "any" or a["status"] == require_status)
        and a.get("superseded_by") is None
    ]

    if not eligible:
        return []

    try:
        query_emb = _embed(issue_text)
    except Exception:
        logger.exception("Embedding failed; falling back to keyword-only")
        query_emb = []

    results = []
    for adr in eligible:
        kw = _keyword_score(query_tokens, adr)
        if query_emb:
            try:
                adr_emb = _embed(adr["title"] + "\n\n" + adr["body"])
                sem = _cosine(query_emb, adr_emb)
            except Exception:
                logger.exception("Embedding ADR %s failed; using keyword only", adr.get("number"))
                sem = 0.0
        else:
            sem = 0.0

        combined = 0.4 * kw + 0.6 * sem if query_emb else kw
        if combined >= confidence_threshold:
            results.append({
                "adr": adr,
                "score": combined,
                "keyword_score": kw,
                "semantic_score": sem,
                "rationale": _build_rationale(adr, issue_text, query_tokens),
            })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results


@tool
def match_pr_to_adrs(
    pr_diff: str,
    pr_description: str,
    adr_index: list[dict],
    scoped_adr_numbers: list[int] | None = None,
    confidence_threshold: float = 0.65,
    require_status: str = "accepted",
) -> list[dict]:
    """Score ADRs against a PR diff + description.

    Args:
        pr_diff: The unified diff text.
        pr_description: PR title + body.
        adr_index: Output of `index_adrs`.
        scoped_adr_numbers: If provided, only evaluate these ADRs (the
            "linked issue ground truth" case). If None, evaluate against
            all eligible ADRs (the unlinked case).
        confidence_threshold: Matches below this are dropped.
        require_status: Only consider ADRs with this status.

    Returns:
        Same shape as match_issue_to_adrs, plus a `mode` field:
            "linked" when scoped_adr_numbers was provided, "unlinked" otherwise.
    """
    query_text = (pr_description or "") + "\n\n" + (pr_diff or "")

    if scoped_adr_numbers is not None:
        scoped = set(scoped_adr_numbers)
        filtered = [a for a in adr_index if a.get("number") in scoped]
        mode = "linked"
    else:
        filtered = [
            a for a in adr_index
            if (require_status == "any" or a["status"] == require_status)
            and a.get("superseded_by") is None
        ]
        mode = "unlinked"

    base = match_issue_to_adrs(query_text, filtered, confidence_threshold, require_status)
    for r in base:
        r["mode"] = mode
    return base
