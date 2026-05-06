// Cedar policies specific to the Adr (ADR-linking) agent.
// Adr reads the repo's ADR library and applies adr-* labels to issues/PRs.
// Cannot modify code, cannot modify ADRs, cannot close/merge.

permit(
    principal == AgentCore::Agent::"adr",
    action == AgentCore::Action::"InvokeTool",
    resource
) when {
    // GitHub — read
    resource.toolName == "github_get_file" ||
    resource.toolName == "github_list_files" ||
    resource.toolName == "github_search_code" ||
    resource.toolName == "github_get_issue" ||
    resource.toolName == "github_list_issues" ||
    resource.toolName == "github_get_pr" ||
    resource.toolName == "github_list_prs" ||
    resource.toolName == "github_get_pr_diff" ||
    resource.toolName == "github_list_pr_files" ||
    resource.toolName == "github_list_commits" ||
    // GitHub — write (labels + comments only; no merges, no closes)
    resource.toolName == "github_add_label" ||
    resource.toolName == "github_remove_label" ||
    resource.toolName == "github_add_comment" ||
    resource.toolName == "github_add_pr_review_comment" ||
    // Bedrock for semantic matching
    resource.toolName == "bedrock_invoke_model"
};

// Hard forbid: modifying ADR files themselves.
forbid(
    principal == AgentCore::Agent::"adr",
    action == AgentCore::Action::"InvokeTool",
    resource
) when {
    (resource.toolName == "github_create_file" ||
     resource.toolName == "github_update_file" ||
     resource.toolName == "github_delete_file" ||
     resource.toolName == "github_create_pr") &&
    resource.path like "*/adr*"
};
