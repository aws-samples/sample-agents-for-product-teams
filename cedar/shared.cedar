// Shared Cedar policies for all agents.
// Forbid destructive operations across the entire fleet.

forbid(
    principal,
    action == AgentCore::Action::"InvokeTool",
    resource
) when {
    resource.toolName == "github_close_issue" ||
    resource.toolName == "github_delete_issue" ||
    resource.toolName == "github_merge_pr" ||
    resource.toolName == "github_close_pr" ||
    resource.toolName == "github_delete_branch" ||
    resource.toolName == "asana_delete_task" ||
    resource.toolName == "asana_delete_project" ||
    resource.toolName == "asana_delete_story"
};
