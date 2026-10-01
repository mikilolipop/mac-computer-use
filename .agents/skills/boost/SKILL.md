---
name: boost
description: >-
  Overhauled multi-agent deep-reasoning and execution mesh for complex engineering tasks.
  Eliminates serial blocking hierarchies (parent waiting on child waiting on grandchild).
  Coordinates parallel peer agents through an atomic shared blackboard, DAG dependencies,
  fail-fast signals, orphan recovery, and ready-tasks discovery.
---

## 2026-09-27 租约接口更新

- `start-task` 只允许领取 pending 任务，返回 `lease_id`。
- `heartbeat`、`complete-task`、`fail-task` 必须传 `--lease <lease_id>`；必须保存本 worker 领取时得到的租约，禁止读取其他 worker 的租约冒用。
- 重试产生新租约，旧 worker 的迟到提交会拒绝。
- completed/aborted 使命不能继续领取任务；所有子任务完成后才允许 complete-mission。
- 下方旧示例中的这些命令应补充 `--lease`。现有正式黑板不会自动迁移。



# /boost: Overhauled Peer-Coordinated Multi-Agent Mesh

## 1. Problem Statement & Architectural Pivot

### The Flaw of Default `/boost`:
In the default Antigravity `/boost` implementation:
1. Orchestrator calls a subagent.
2. Orchestrator halts and sits completely idle, blocking on the subagent.
3. The subagent calls another subagent (nested depth ≥ 2) and also sits idle.
4. Each step incurs 20–35s inference reasoning latency plus network RTT.
5. Sibling agents cannot see each other or share context; messages must bubble all the way up and down the hierarchy.
6. A single 4-step task easily explodes to 15+ minutes of pure idle waiting.

### The Overhauled Architecture:
- **Flat Peer Mesh (Max Depth = 1)**: Subagents NEVER spawn subagents. The hierarchy is strictly flat.
- **Active Orchestrator (Zero Idle Waiting)**: When subagents are running, the Orchestrator works on test harnesses, peripheral inspections, or parallel tracks.
- **Dynamic Wave Scheduling (`ready-tasks`)**: Orchestrator queries unblocked tasks and dispatches all parallelizable tasks at once.
- **Atomic Shared Blackboard (`.agents/boost/blackboard.json`)**: All state, task DAGs, discovered facts, and blocker signals are shared via a fast, local, flock-protected blackboard with unified reader-writer locking.
- **Auto-Discovery of Project Root**: CLI automatically discovers workspace root blackboard regardless of current working subdirectory.
- **Cycle & Self-Dependency Protection**: DAG cycles are caught and rejected on task creation before deadlocks can form.
- **Cascading Blocked Propagation**: When a prerequisite fails, downstream dependent tasks immediately transition to `blocked`.
- **Worker Crash & Orphan Task Recovery (`reclaim-orphans`)**: Stalled tasks exceeding heartbeat timeout are automatically reclaimed or failed fast.
- **Fail-Fast Signal Bus (`check-signals --fail-fast`)**: Broadcasts `FATAL_BLOCKER` signals immediately and exits with non-zero code to halt pipelines.
- **Budget Guardrails (Strict Tool Budget ≤ 5)**: Agents must batch tool calls and never enter cyclical probing loops.

---

## 2. Multi-Agent Roles & Topography

```
                     ┌────────────────────────┐
                     │  Leader / Orchestrator │ (DAG Planning, Dynamic Wave Scheduling)
                     └───────────┬────────────┘
                                 │
     ┌───────────────────────────┼───────────────────────────┐
     ▼                           ▼                           ▼
┌──────────────┐          ┌──────────────┐          ┌───────────────────┐
│ Investigator │          │ Implementer  │          │  Skeptic Auditor  │
│  (Discovery) │          │  (Code/Fix)  │          │ (Adversarial Test)│
└──────┬───────┘          └──────┬───────┘          └─────────┬─────────┘
       │                         │                            │
       └─────────────────────────┴────────────────────────────┘
                                 ▲
                                 │ (Peer read/write via scripts/boost_coordinator.py)
                     ┌───────────┴────────────┐
                     │    Shared Blackboard   │
                     │  (.agents/boost/*.json)│
                     └────────────────────────┘
```

### Role Specifications:
1. **Leader / Orchestrator**:
   - Decomposes the user request into an actionable Task DAG.
   - Initializes the blackboard: `python3 .agents/skills/boost/scripts/boost_coordinator.py init --task "<task>" --budget 30`.
   - Queries executable tasks: `python3 .agents/skills/boost/scripts/boost_coordinator.py ready-tasks`.
   - Dispatches independent tasks **in parallel** via subagent calls.
   - Supervises mesh health and reclaims stalled tasks: `python3 .agents/skills/boost/scripts/boost_coordinator.py reclaim-orphans --timeout 60`.
   - Synthesizes the final verified delivery and completes mission: `python3 .agents/skills/boost/scripts/boost_coordinator.py complete-mission --summary "<summary>"`.

2. **Investigator (Code Archaeologist)**:
   - Tool budget: Strictly ≤ 3 calls.
   - Locates exact files, AST signatures, dependencies, and reproduction conditions.
   - Writes discovered facts to blackboard: `python3 .agents/skills/boost/scripts/boost_coordinator.py post-fact --key "<k>" --val "<v>" --sender "investigator"`.
   - Marks task complete: `python3 .agents/skills/boost/scripts/boost_coordinator.py complete-task --id "<tid>" --output "<summary>"`.

3. **Implementer (Precision Builder)**:
   - Consumes facts directly from the blackboard without waiting for an orchestrator relay (`get-fact` / `list-facts`).
   - Marks task started: `python3 .agents/skills/boost/scripts/boost_coordinator.py start-task --id "<tid>" --owner "implementer"`.
   - Sends periodic heartbeats during long edits: `python3 .agents/skills/boost/scripts/boost_coordinator.py heartbeat --id "<tid>"`.
   - Modifies files using targeted, atomic edits.
   - Verifies syntax locally before completion.

4. **Skeptic Auditor (Adversarial Verifier)**:
   - Does NOT trust happy paths or "it should work" statements.
   - Actively tries to break the implementation with edge cases: empty inputs, boundary conditions, malformed packets, concurrency races.
   - Runs the repository's test suite and new regression tests.
   - If tests fail, posts a blocker: `python3 .agents/skills/boost/scripts/boost_coordinator.py fail-task --id "<tid>" --error "<error>"`.

---

## 3. Workflow Execution Phases

### Phase 1: Rapid DAG Initialization (< 10 seconds)
1. Orchestrator inspects `<original_task>`.
2. Orchestrator registers tasks and dependencies:
   ```bash
   python3 .agents/skills/boost/scripts/boost_coordinator.py init --task "Task Description"
   python3 .agents/skills/boost/scripts/boost_coordinator.py add-task --id "T1_investigate" --title "Identify affected symbols & dependencies" --owner "investigator"
   python3 .agents/skills/boost/scripts/boost_coordinator.py add-task --id "T2_harness" --title "Create regression test harness" --owner "skeptic"
   python3 .agents/skills/boost/scripts/boost_coordinator.py add-task --id "T3_implement" --title "Apply core fix" --owner "implementer" --deps "T1_investigate"
   python3 .agents/skills/boost/scripts/boost_coordinator.py add-task --id "T4_verify" --title "Run deep regression & boundary verification" --owner "skeptic" --deps "T3_implement,T2_harness"
   ```

### Phase 2: Parallel Wave Dispatch
- Orchestrator checks `ready-tasks`.
- Concurrently dispatches all unblocked tasks (`T1_investigate` and `T2_harness`).
- Investigator records findings using `post-fact`.
- Skeptic creates the test harness that reproduces the problem or defines edge cases.

### Phase 3: Pipelined Implementation
- As soon as `T1_investigate` completes, `ready-tasks` unlocks `T3_implement`.
- Implementer reads facts (`get-fact` or `list-facts --prefix ...`) and makes the code changes.
- Implementer marks `complete-task` upon syntax and local verification.

### Phase 4: Adversarial Verification & Report
- Skeptic executes all tests against the modified codebase.
- Checks edge cases explicitly.
- Orchestrator exports summary and seals mission:
   ```bash
   python3 .agents/skills/boost/scripts/boost_coordinator.py complete-mission --summary "All verification tests passed"
   python3 .agents/skills/boost/scripts/boost_coordinator.py export-summary
   ```

---

## 4. Blackboard CLI Cheat Sheet

| Command | Action |
| :--- | :--- |
| `init --task "<desc>"` | Initialize new coordination blackboard |
| `status [--json]` | View human-readable or JSON status of all agents & tasks |
| `add-task --id "<id>" --title "<t>" --owner "<role>" [--deps "id1,id2"]` | Register task with cycle & self-dependency validation |
| `ready-tasks [--json]` | List all pending tasks whose dependencies are satisfied |
| `start-task --id "<id>"` | Mark task in progress (validates dependencies are met) |
| `heartbeat --id "<id>"` | Update worker liveness timestamp |
| `reclaim-orphans [--timeout 120] [--retry]` | Reclaim stalled/crashed worker tasks |
| `complete-task --id "<id>" --output "<summary>"` | Mark task completed and record summary |
| `fail-task --id "<id>" --error "<reason>"` | Mark task failed, cascade blocked state, and post blocker signal |
| `post-fact --key "<k>" --val "<v>" --sender "<role>"` | Share discovery with all peers |
| `get-fact --key "<k>"` | Read a shared discovery |
| `list-facts [--prefix "<p>"] [--sender "<s>"]` | List and filter shared discoveries |
| `signal --type <BLOCKER\|ALERT\|ABORT> --msg "<m>"` | Broadcast urgent signal to all peers |
| `check-signals [--fail-fast]` | Check blocker signals (exits with code 2 on blockers if fail-fast) |
| `complete-mission --summary "<s>"` | Seal mission state as completed |
| `abort-mission --reason "<r>"` | Abort mission and broadcast ABORT signal |
| `export-summary [--out <file>]` | Generate final markdown coordination report |

---

## 5. Absolute Invariants (Permanent Strategy Principles)
1. **No Hierarchical Nesting**: Max agent depth is 1. No child calls another child.
2. **Tool Budget Limit**: Max 5 tool calls per agent turn. No loops.
3. **No Phantom Success**: Every assertion must be proven by test output; never report unverified success.
4. **Preserve User Field State**: Never overwrite uncommitted user code or alter git history without explicit confirmation.
