---
name: record-and-replay
description: Record the user's actions on their Mac with Record & Replay, and turn it into a reusable ChatGPT skill from the captured event stream.
---

# Record & Replay

Record & Replay lets ChatGPT learn a user-demonstrated macOS workflow and turn it into a reusable skill. Use it when the user asks you to watch them perform a task, record a workflow, or create or refine a skill from their demonstration.

## Recording Workflow

- Use `event_stream_start` only when the user is ready to begin recording.
- Starting asks the user to confirm before capture begins.
- After `event_stream_start` succeeds, do not sleep, poll, or wait in a loop for the user to finish. End your turn and ask the user to tell you when they are done recording and tell them what the time limit is on recording.
- Use `event_stream_status` only when the user asks for status or returns after recording; do not use it to poll while waiting.
- Use `event_stream_stop` when recording is complete.
- When the user says they are done recording, read the returned `metadataPath` and `eventsPath` from disk with normal filesystem tools and inspect the captured events before responding.
- When the user says they cancelled recording, do not call `event_stream_stop` again or attempt to use the event stream. You may read `session.json` if needed to confirm that its `endReason` is `recording_controls_cancelled`; acknowledge the cancellation without creating or updating a skill.
- Before creating or refining a skill, check whether the recording and the user's request clearly establish the reusable workflow, its intended outcome, and which demonstrated values should become skill inputs rather than fixed details. If any ambiguity would materially affect the skill, explain what is unclear, ask concise follow-up questions, and wait for the answers.
- Otherwise, if the recording contains enough information to identify a reusable workflow, create or refine a skill for that workflow by default even if the user did not explicitly ask for one; do not stop after providing a summary, replay plan, runbook, or suggestion to create one.
- The MCP server does not expose event-stream contents directly.

## Concurrent Recording

Record & Replay supports one active recording at a time. If `event_stream_start` reports an active recording, do not restart it. Explain that another recording is already in progress and ask whether the user wants to use that active recording or wait until it is stopped.

## Interpreting Events

- Treat `events.jsonl` as the primary evidence. `session.json` gives paths and session timing only.
- Each event has app/window attribution when available. Use those fields to understand where the event happened; AX payloads may be full trees or diffs for the relevant window.
- AX diff payloads use compact render syntax with ~, +, and - representing changed, added, and removed elements, respectively.
- Pay special attention to selection events, selected text, focused elements, and mouse & keyboard targets. If the user asks a question or refers to the content they are looking at on-screen, selected/focused/targeted content is often the best clue, though visible surrounding UI can also matter.
- Do not include sensitive information from recorded events in summaries or generated skills. Treat passwords, OTPs, API keys, SSNs/passports, financial account/card numbers, and private personal, medical, legal, or HR details as sensitive; use placeholders or generic descriptions when the workflow shape needs to mention them.

## Creating Skills

Before creating or refining a skill, read and follow the `skill-creator` skill for guidance on structure, reusable resources, and structural validation. Completing its workflow only verifies that the skill is well-formed; it does not establish that the skill can successfully reproduce a Computer Use workflow.

Create or refine an actual discoverable skill, not only a standalone Markdown runbook or replay-plan draft. Complete the skill-creator workflow, including validation, before reporting that the skill was created.

When creating a skill from a recording, treat the recording as evidence of the user's intended outcome, not a requirement to reproduce every UI action. Check whether an available connector or dedicated tool supports the task; prefer it for stable semantic operations such as creating a Google Doc or calendar event. Use Computer Use for unsupported UI interactions, visually dependent verification, or when manipulating the interface is itself the task. A skill may combine connectors and Computer Use. When using Computer Use, name it explicitly, describe stable app/window/control targets and interactions, include verification steps, and avoid coordinate-only replay unless the event stream gives no better target.

After creating or refining the skill, give the user a concise plain-language summary of its steps, inputs, and important assumptions. Make the summary sufficient for the user to review the workflow and offer corrections without needing to read the full `SKILL.md`.
