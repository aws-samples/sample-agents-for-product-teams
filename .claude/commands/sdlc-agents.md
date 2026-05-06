---
description: Install and configure the SDLC Agent Fleet into a target project
argument-hint: "[target-repo-path-or-url]"
---

You are about to drive the SDLC Agent Fleet install flow. This repo is the **installer** (it contains the agent source, infra templates, and skills); the user wants to wire the fleet into a **different repo** — the "target project".

## Target project

The user passed `$ARGUMENTS` as the target. Resolve it to a concrete working location:

- **If `$ARGUMENTS` is empty:** ask the user where the target project is. Accept either a local filesystem path or a git remote URL (HTTPS or SSH). Do not assume the current working directory is the target — this repo is the installer, and running the flow against it will misdetect things like ADRs and CI workflows.
- **If `$ARGUMENTS` looks like a local path:** confirm it exists, is a git repo, and print its configured `origin` remote back to the user for confirmation.
- **If `$ARGUMENTS` looks like a remote URL** (starts with `git@`, `https://`, `ssh://`, or matches `<host>:<org>/<repo>`): ask the user for a local clone path — either an existing checkout you should use, or a parent directory where you should `git clone` the repo. Never clone outside a location the user named.

Record the resolved absolute local path as `TARGET_REPO`. Every filesystem check in the install flow (ADR directory detection, `.github/workflows/` inspection, `.sdlc-agents/selection.yaml` writes, etc.) must be rooted at `TARGET_REPO`, **not** at the cwd of this session.

Record the configured `origin` remote as `TARGET_REMOTE` (from `git -C "$TARGET_REPO" remote get-url origin`). Integration steps that need an owner/repo slug (GitHub App install, Actions Variables, OIDC trust policy) read from there.

If the target repo is dirty (`git -C "$TARGET_REPO" status --porcelain` non-empty), tell the user before you start writing files into it.

## Install flow

The authoritative instructions live in **this** repo (the installer) at `skills/sdlc-agents/SKILL.md`. Read it now and follow it exactly — it walks toolchain discovery → agent selection → AWS provisioning → integration wiring → webhook registration → smoke tests.

Each step in that flow delegates to a narrower skill under `skills/sdlc-agents-*/SKILL.md` (e.g. `skills/sdlc-agents-select/SKILL.md`). When the top-level flow says "invoke sdlc-agents-select", read the matching file from this installer repo and follow its checklist. Do not try to invoke them via the `Skill` tool — they are not registered plugins, they are repo-local markdown.

Two reminders that are easy to forget once you are deep in the flow:

1. **All target-project filesystem operations use `TARGET_REPO`**, never the cwd. That includes reading ADRs, writing `.sdlc-agents/selection.yaml`, reading/writing `.github/workflows/`, and `git` commands.
2. **All installer-side reads** (agent source in `agents/`, Cedar policies in `cedar/`, SAM templates in `infra/`, the skill files themselves) come from the **current working directory** — the clone of this installer repo.

Start by resolving `TARGET_REPO` and `TARGET_REMOTE` per the "Target project" section above, then begin Step 1 (toolchain discovery) from `skills/sdlc-agents/SKILL.md`.
