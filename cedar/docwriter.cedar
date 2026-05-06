// Cedar policies specific to the Docwriter (documentation) agent.
// Docwriter can read broadly and write docs (PRs, issues, comments).
// Cannot modify code, merge, close, or delete.

permit(
    principal == AgentCore::Agent::"docwriter",
    action == AgentCore::Action::"InvokeTool",
    resource
) when {
    // GitHub — read (code, PRs, issues, files, search)
    resource.toolName == "github_get_file" ||
    resource.toolName == "github_list_files" ||
    resource.toolName == "github_get_pr" ||
    resource.toolName == "github_list_prs" ||
    resource.toolName == "github_get_issue" ||
    resource.toolName == "github_list_issues" ||
    resource.toolName == "github_search_code" ||
    resource.toolName == "github_list_commits" ||
    resource.toolName == "github_list_tags" ||
    resource.toolName == "github_get_release" ||
    // GitHub — write (doc PRs, issues, comments only)
    resource.toolName == "github_create_pr" ||
    resource.toolName == "github_create_issue" ||
    resource.toolName == "github_add_comment" ||
    resource.toolName == "github_add_label" ||
    // Asana — read (feature context)
    resource.toolName == "asana_get_task" ||
    resource.toolName == "asana_list_tasks" ||
    resource.toolName == "asana_get_task_stories" ||
    resource.toolName == "asana_search" ||
    // Asana — write (doc status comments, doc tasks)
    resource.toolName == "asana_add_comment" ||
    resource.toolName == "asana_create_task" ||
    // Slack — write (doc notifications)
    resource.toolName == "slack_post_message"
};
