---
description: Install, configure, and onboard the SDLC Agent Fleet into this project
---

You are about to drive the SDLC Agent Fleet install flow for the user.

The authoritative instructions live in this repo at `skills/sdlc-agents/SKILL.md`. Read that file now and follow it exactly — it is a conversational install flow that discovers the user's toolchain, proposes an agent subset, provisions AWS, wires integrations, registers triggers, and verifies.

Each step in that skill delegates to a narrower skill under `skills/sdlc-agents-*/SKILL.md` (e.g. `skills/sdlc-agents-select/SKILL.md`, `skills/sdlc-agents-provision-aws/SKILL.md`). When the top-level flow tells you to invoke one of those, read the matching file in this repo and follow its checklist. Do not attempt to invoke them via the `Skill` tool — they aren't registered plugins, they're repo-local markdown.

Start by reading `skills/sdlc-agents/SKILL.md` and then begin Step 1 (toolchain discovery) with the user.
