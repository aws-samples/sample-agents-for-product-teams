// Cedar policies specific to the Researcher (business analyst) agent.
// Researcher works exclusively through Asana. Can read broadly, create/update
// tasks and comments, use web search and code execution.
// No GitHub writes, no merge/close/delete.

permit(
    principal == AgentCore::Agent::"researcher",
    action == AgentCore::Action::"InvokeTool",
    resource
) when {
    // Asana — read
    resource.toolName == "asana_get_task" ||
    resource.toolName == "asana_list_tasks" ||
    resource.toolName == "asana_get_task_stories" ||
    resource.toolName == "asana_get_project" ||
    resource.toolName == "asana_list_projects" ||
    resource.toolName == "asana_search" ||
    // Asana — write (create, update, comment only)
    resource.toolName == "asana_create_task" ||
    resource.toolName == "asana_update_task" ||
    resource.toolName == "asana_add_comment" ||
    // Web search — competitive intelligence and market research
    resource.toolName == "web_search"
};

// Code execution — quantitative analysis (RICE, clustering, visualizations)
permit(
    principal == AgentCore::Agent::"researcher",
    action == AgentCore::Action::"ExecuteCode",
    resource
);
