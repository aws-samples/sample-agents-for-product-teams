"""API documentation generation tool.

Structured task tool — returns a prompt that guides the agent through
reading an OpenAPI spec (or scanning code) and producing API reference docs.
The actual GitHub file reads and PR creation happen via MCP tools.
"""

from strands import tool


@tool
def generate_api_docs(
    spec_source: str,
    output_format: str = "markdown",
    sections: str = "",
) -> str:
    """Generate API reference documentation from an OpenAPI spec or code.

    The agent should use this tool when asked to create or update API docs.
    It returns a structured workflow for the agent to follow.

    Args:
        spec_source: Path to OpenAPI spec file in the repo (e.g. 'openapi.yaml'),
            or 'scan' to discover endpoints from route definitions in code.
        output_format: Target format — 'markdown', 'docusaurus', or 'mintlify'.
        sections: Comma-separated list of sections to generate (e.g. 'auth,search').
            Empty string means all sections.

    Returns:
        Instructions for the agent to follow when generating API docs.
    """
    section_filter = ""
    if sections:
        section_filter = (
            f"\nScope: Only generate docs for these sections: {sections}. "
            "Skip all other endpoints.\n"
        )

    if spec_source == "scan":
        source_step = (
            "1. Use github_search_code to find route definitions "
            "(e.g. @app.route, router.get, @api_view).\n"
            "2. Read each route handler file to extract: method, path, parameters, "
            "request body schema, response schema, and status codes.\n"
        )
    else:
        source_step = (
            f"1. Use github_get_file to read the OpenAPI spec at '{spec_source}'.\n"
            "2. Parse the spec to extract all endpoint definitions.\n"
        )

    return (
        f"Generate API reference documentation.\n"
        f"Source: {spec_source}\n"
        f"Format: {output_format}\n"
        f"{section_filter}\n"
        f"Steps:\n"
        f"{source_step}"
        "3. For EACH endpoint, produce:\n"
        "   - HTTP method and path\n"
        "   - One-line description\n"
        "   - Parameters table (name, type, required, description, example)\n"
        "   - Request body schema with example JSON\n"
        "   - Response schema with example JSON for success and error cases\n"
        "   - Error codes table (status, meaning, resolution)\n"
        "   - curl example AND Python SDK example\n"
        "4. Group endpoints by tag or path prefix.\n"
        "5. Add a table of contents at the top.\n"
        "6. Open a PR with the generated docs in the docs/ directory.\n"
        "   Label the PR 'docwriter-generated'.\n"
        "7. Post a summary of what was generated as a comment on the PR."
    )
