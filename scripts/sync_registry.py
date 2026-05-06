"""Sync .dispatch/agents.yaml to the SSM registry, resolving runtime ARNs.

The source file uses placeholder ARNs like "${WORKITEMS_RUNTIME_ARN}".
This script looks up each agent's runtime by name via the AgentCore
control plane and substitutes the real ARN before writing to SSM.

Run locally or from CI. Idempotent. Fails if any agent has a placeholder
that cannot be resolved.

Usage:
    python scripts/sync_registry.py [--stage dev] [--region us-west-2] [--dry-run]
"""

import argparse
import logging
import re
import sys
from pathlib import Path

import boto3

logger = logging.getLogger("sync_registry")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

PLACEHOLDER_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def resolve_runtime_arn(agentcore, agent_name: str) -> str:
    """Look up an agent's runtime ARN by name. Raises if not found."""
    paginator = agentcore.get_paginator("list_agent_runtimes")
    for page in paginator.paginate():
        for rt in page.get("agentRuntimes", []):
            if rt.get("agentRuntimeName") == agent_name:
                return rt["agentRuntimeArn"]
    raise LookupError(
        f"No AgentCore runtime named '{agent_name}' found. "
        f"Create it before syncing the registry."
    )


def render_registry(yaml_text: str, agentcore) -> str:
    """Replace every ${*_RUNTIME_ARN} placeholder with the real ARN.

    Placeholder naming convention: ${<AGENT_NAME>_RUNTIME_ARN} where
    <AGENT_NAME> uppercased matches the agent's runtime name.
    """
    import yaml

    registry = yaml.safe_load(yaml_text)
    agents = registry.get("agents", {}) or {}

    for agent_id, config in agents.items():
        arn = config.get("runtime_arn", "")
        match = PLACEHOLDER_RE.fullmatch(arn.strip('"').strip("'"))
        if not match:
            continue

        placeholder = match.group(1)
        expected = f"{agent_id.upper()}_RUNTIME_ARN"
        if placeholder != expected:
            raise ValueError(
                f"Agent '{agent_id}' uses placeholder ${{{placeholder}}} "
                f"but convention requires ${{{expected}}}."
            )

        resolved = resolve_runtime_arn(agentcore, agent_id)
        logger.info("Resolved %s -> %s", agent_id, resolved)
        config["runtime_arn"] = resolved

    leftover = PLACEHOLDER_RE.findall(yaml.safe_dump(registry))
    if leftover:
        raise RuntimeError(
            f"Registry still has unresolved placeholders after sync: {leftover}"
        )

    return yaml.safe_dump(registry, sort_keys=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", default="dev")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument(
        "--source",
        default=Path(__file__).parent.parent / ".dispatch" / "agents.yaml",
        type=Path,
    )
    parser.add_argument("--dry-run", action="store_true", help="Print rendered YAML; do not write to SSM.")
    args = parser.parse_args()

    if not args.source.exists():
        logger.error("Source file not found: %s", args.source)
        return 1

    agentcore = boto3.client("bedrock-agentcore-control", region_name=args.region)
    ssm = boto3.client("ssm", region_name=args.region)

    rendered = render_registry(args.source.read_text(), agentcore)

    if args.dry_run:
        sys.stdout.write(rendered)
        return 0

    param_name = f"/sdlc-agents/{args.stage}/registry"
    ssm.put_parameter(
        Name=param_name,
        Value=rendered,
        Type="String",
        Overwrite=True,
    )
    logger.info("Wrote registry to SSM %s (%d bytes)", param_name, len(rendered))
    return 0


if __name__ == "__main__":
    sys.exit(main())
