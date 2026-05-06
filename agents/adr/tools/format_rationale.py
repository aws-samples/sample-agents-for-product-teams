"""Format the consolidated ADR rationale comment for issues and PRs.

The agent calls this after matching to build the single comment it will
post. Keeping formatting in a tool (rather than in the prompt) makes it
deterministic and reviewable.
"""

from strands import tool


SIGNATURE = "🏛️ **[ADR Agent]**"


def _label_for(adr: dict) -> str:
    """Return the GitHub label string for an ADR (e.g. `adr-0012`)."""
    n = adr.get("number")
    if n is None:
        return "adr-unknown"
    return f"adr-{n:04d}"


@tool
def format_tag_issue_comment(matches: list[dict]) -> dict:
    """Format the Mode 1 (TAG_ISSUE) rationale comment.

    Args:
        matches: Output of match_issue_to_adrs, already filtered by threshold.

    Returns:
        {
          "comment": str,           # full markdown comment, signed
          "labels": list[str],      # labels to apply (adr-NNNN)
        }
    """
    if not matches:
        return {
            "comment": (f"{SIGNATURE}\n\n"
                        "Scanned the ADR library. No strong matches for this issue. "
                        "If you believe an ADR applies that I missed, reply with its "
                        "number and I'll reconsider."),
            "labels": [],
        }

    lines = [SIGNATURE, "", "This work is governed by the following architecture decisions:", ""]
    labels = []
    for m in matches:
        adr = m["adr"]
        label = _label_for(adr)
        labels.append(label)
        num_str = f"{adr['number']:04d}" if adr.get("number") is not None else "unknown"
        lines.append(
            f"- **ADR-{num_str}** — {adr['title']} (status: {adr['status']})\n"
            f"  *{m['rationale']}*"
        )
    lines.append("")
    lines.append(f"Applied labels: {', '.join(f'`{l}`' for l in labels)}.")
    lines.append("")
    lines.append("If any of these don't apply, remove the label — "
                 "I won't re-apply a label a human has removed.")

    return {"comment": "\n".join(lines), "labels": labels}


@tool
def format_pr_review_summary(matches: list[dict], mode: str, linked_issues: list[int] = None) -> str:
    """Format the summary comment on a PR review.

    Args:
        matches: Output of match_pr_to_adrs.
        mode: "linked" or "unlinked".
        linked_issues: Optional list of issue numbers (for linked mode).

    Returns:
        The summary comment text.
    """
    if not matches:
        if mode == "linked":
            scope = (f"against ADRs from linked issue(s): "
                     f"{', '.join(f'#{i}' for i in (linked_issues or []))}")
        else:
            scope = "against inferred-candidate ADRs (no linked issue found)"
        return (f"{SIGNATURE}\n\n"
                f"Reviewed {scope}. No conflicts found.")

    bullets = []
    for m in matches:
        adr = m["adr"]
        num_str = f"{adr['number']:04d}" if adr.get("number") is not None else "unknown"
        prefix = "[suggested] " if mode == "unlinked" else ""
        bullets.append(
            f"- {prefix}**ADR-{num_str}** — {adr['title']} (status: {adr['status']})"
        )

    if mode == "linked":
        header = (f"Reviewed this PR against ADRs from linked issue(s): "
                  f"{', '.join(f'#{i}' for i in (linked_issues or []))}.")
    else:
        header = ("Reviewed this PR against candidate ADRs inferred from the diff. "
                  "No linked issue, so these findings are **suggested** — consider "
                  "adding `Closes #N` to your PR body for a scoped review.")

    return (f"{SIGNATURE}\n\n"
            f"{header}\n\n"
            f"ADRs evaluated:\n" + "\n".join(bullets) + "\n\n"
            "Inline review comments are posted on the specific diff hunks.")
