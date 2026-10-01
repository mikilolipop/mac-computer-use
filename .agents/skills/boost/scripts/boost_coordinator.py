#!/usr/bin/env python3
"""
Boost Coordinator - Real Multi-Agent Mesh Coordination Engine for Antigravity /boost.

Eliminates the serial blocking hierarchy ("parent calls subagent then does nothing
while child calls grandchild then waits"). Provides atomic blackboard operations,
DAG task tracking, shared memory, and instant blocker signaling.
"""

import os
import sys
import json
import time
import uuid
import fcntl
import argparse
from typing import Dict, Any, Optional, List, Set

DEFAULT_BOARD_REL_PATH = os.path.join(".agents", "boost", "blackboard.json")

def get_board_path(custom_path: Optional[str] = None) -> str:
    """
    Resolve absolute path to blackboard.json.
    Traverses parent directories to discover project root marker
    if invoked from subdirectories.
    """
    if custom_path:
        return os.path.abspath(custom_path)
    env_path = os.environ.get("BOOST_BLACKBOARD")
    if env_path:
        return os.path.abspath(env_path)

    curr = os.path.abspath(os.getcwd())
    while True:
        candidate = os.path.join(curr, DEFAULT_BOARD_REL_PATH)
        if os.path.exists(candidate):
            return candidate
        # Check project root indicators
        if any(os.path.exists(os.path.join(curr, marker)) for marker in [".agents", "strategy_log.md", ".git"]):
            return candidate
        parent = os.path.dirname(curr)
        if parent == curr:
            break
        curr = parent

    return os.path.abspath(DEFAULT_BOARD_REL_PATH)

class AtomicBlackboard:
    """
    Thread-safe and process-safe blackboard with unified file locking.
    Uses shared lock for readers and exclusive lock for writers on a dedicated .lock file.
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.dirpath = os.path.dirname(filepath)
        if self.dirpath and not os.path.exists(self.dirpath):
            os.makedirs(self.dirpath, exist_ok=True)
        self.lock_file = f"{self.filepath}.lock"

    def _open_lock(self):
        # Open in append/read mode without truncating
        return open(self.lock_file, "a+", encoding="utf-8")

    def read(self) -> Dict[str, Any]:
        if not os.path.exists(self.filepath):
            return {}
        with self._open_lock() as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_SH)
            try:
                if not os.path.exists(self.filepath):
                    return {}
                with open(self.filepath, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if not content:
                        return {}
                    return json.loads(content)
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    def update(self, mutator_func) -> Dict[str, Any]:
        """Atomically read, mutate in place, and atomic write back under exclusive lock."""
        with self._open_lock() as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                data = {}
                if os.path.exists(self.filepath):
                    with open(self.filepath, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        if content:
                            data = json.loads(content)
                updated_data = mutator_func(data)
                
                # Atomic temp file write + rename on same directory
                temp_path = f"{self.filepath}.tmp.{os.getpid()}.{time.time_ns()}"
                with open(temp_path, "w", encoding="utf-8") as tf:
                    json.dump(updated_data, tf, indent=2, ensure_ascii=False)
                    tf.flush()
                    os.fsync(tf.fileno())
                os.replace(temp_path, self.filepath)
                return updated_data
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

# ----------------- DAG Helper Functions -----------------

def _detect_cycle(graph: Dict[str, List[str]], new_id: str) -> Optional[List[str]]:
    """
    Check if directed graph has a cycle using DFS.
    Returns cycle path list if cycle detected, else None.
    """
    visited = set()
    rec_stack = []

    def dfs(node: str) -> Optional[List[str]]:
        visited.add(node)
        rec_stack.append(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                cycle = dfs(neighbor)
                if cycle:
                    return cycle
            elif neighbor in rec_stack:
                cycle_start = rec_stack.index(neighbor)
                return rec_stack[cycle_start:] + [neighbor]
        rec_stack.pop()
        return None

    for n in graph:
        cycle = dfs(n)
        if cycle:
            return cycle
    return None

def _propagate_blocked(tasks: Dict[str, Any], failed_id: str):
    """Recursively marks pending dependent tasks as blocked."""
    for tid, t in tasks.items():
        if t.get("status") == "pending" and failed_id in t.get("deps", []):
            t["status"] = "blocked"
            t["blocked_by"] = failed_id
            _propagate_blocked(tasks, tid)

def require_active(data):
    if data.get("task", {}).get("status") != "in_progress":
        raise ValueError("Mission must be in_progress.")


def require_lease(data, task, lease):
    require_active(data)
    if task.get("status") != "in_progress" or not lease or task.get("lease_id") != lease:
        raise ValueError("Task is not running under this lease; stale worker result rejected.")


# ----------------- Commands -----------------

def cmd_init(args):
    board = AtomicBlackboard(get_board_path(args.board))
    init_state = {
        "version": "2.1.0",
        "created_at": time.time(),
        "updated_at": time.time(),
        "task": {
            "title": args.task,
            "status": "in_progress",
            "token_budget": args.budget,
            "max_hierarchy_depth": 1,  # Strictly flat! No child-of-child nesting
            "active_mode": "peer_mesh",
            "completed_at": None,
            "summary": None,
            "abort_reason": None
        },
        "tasks": {},
        "shared_facts": {},
        "signals": [],
        "artifacts": []
    }
    def mutator(_):
        return init_state
    board.update(mutator)
    print(json.dumps({"success": True, "board": board.filepath, "task": args.task}))

def cmd_status(args):
    board = AtomicBlackboard(get_board_path(args.board))
    data = board.read()
    if not data:
        print(json.dumps({"success": False, "error": f"Blackboard not found at {board.filepath}"}))
        sys.exit(1)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    # Formatted human-readable output
    t = data.get("task", {})
    print("=" * 60)
    print(f"BOOST MESH COORDINATION STATUS: {t.get('title')}")
    print(f"Mission Status: {t.get('status').upper()} | Budget: {t.get('token_budget')} | Depth Cap: {t.get('max_hierarchy_depth')}")
    if t.get("summary"):
        print(f"Mission Summary: {t.get('summary')}")
    if t.get("abort_reason"):
        print(f"Mission Abort Reason: {t.get('abort_reason')}")
    print("=" * 60)
    
    print("\n[ACTIVE SIGNALS]")
    signals = data.get("signals", [])
    if not signals:
        print("  None")
    for s in signals[-5:]:
        print(f"  [{s.get('type')}] ({s.get('sender')}): {s.get('message')}")

    print("\n[TASK DAG]")
    tasks = data.get("tasks", {})
    if not tasks:
        print("  No subtasks registered yet.")
    for tid, tinfo in tasks.items():
        st = tinfo.get("status")
        sym = {
            "pending": "[ ]",
            "in_progress": "[/]",
            "completed": "[x]",
            "failed": "[!]",
            "blocked": "[-]"
        }.get(st, "[?]")
        blocked_info = f" (blocked by: {tinfo.get('blocked_by')})" if st == "blocked" else ""
        print(f"  {sym} {tid} ({tinfo.get('owner', 'unassigned')}): {tinfo.get('title')} [{st}]{blocked_info}")
        if tinfo.get("deps"):
            print(f"      depends on: {', '.join(tinfo.get('deps'))}")
        if tinfo.get("output"):
            print(f"      output: {tinfo.get('output')[:80]}...")
        if tinfo.get("error"):
            print(f"      error: {tinfo.get('error')[:80]}...")

    print("\n[SHARED FACTS]")
    facts = data.get("shared_facts", {})
    if not facts:
        print("  None")
    for k, v in facts.items():
        print(f"  * {k} = {v.get('value')} (posted by {v.get('posted_by')})")

def cmd_add_task(args):
    board = AtomicBlackboard(get_board_path(args.board))
    deps = [d.strip() for d in args.deps.split(",") if d.strip()]
    if args.id in deps:
        raise ValueError(f"Task '{args.id}' cannot depend on itself.")

    def mutator(data):
        require_active(data)
        if not data:
            raise ValueError("Blackboard not initialized. Run init first.")
        tasks = data.setdefault("tasks", {})
        if args.id in tasks:
            raise ValueError(f"Task '{args.id}' already exists in DAG.")

        # DAG cycle validation
        graph = {tid: list(tinfo.get("deps", [])) for tid, tinfo in tasks.items()}
        graph[args.id] = deps
        cycle = _detect_cycle(graph, args.id)
        if cycle:
            raise ValueError(f"Dependency cycle detected: {' -> '.join(cycle)}")

        tasks[args.id] = {
            "id": args.id,
            "title": args.title,
            "owner": args.owner,
            "deps": deps,
            "status": "pending",
            "created_at": time.time(),
            "started_at": None,
            "last_heartbeat_at": None,
            "completed_at": None,
            "output": None,
            "error": None,
            "retry_count": 0
        }
        data["updated_at"] = time.time()
        return data

    board.update(mutator)
    print(json.dumps({"success": True, "task_id": args.id, "status": "pending"}))

def cmd_ready_tasks(args):
    """List tasks that have no unmet dependencies and are ready to execute concurrently."""
    board = AtomicBlackboard(get_board_path(args.board))
    data = board.read()
    tasks = data.get("tasks", {})
    ready = []
    for tid, t in tasks.items():
        if t.get("status") == "pending":
            deps = t.get("deps", [])
            if all(tasks.get(d, {}).get("status") == "completed" for d in deps):
                ready.append(t)
    if args.json:
        print(json.dumps({"success": True, "ready_tasks": ready, "count": len(ready)}, indent=2, ensure_ascii=False))
    else:
        print(f"READY TASKS ({len(ready)}):")
        if not ready:
            print("  None (waiting on in-progress tasks or dependencies)")
        for t in ready:
            print(f"  * {t['id']} [{t['owner']}]: {t['title']} (deps: {t.get('deps', [])})")

def cmd_start_task(args):
    board = AtomicBlackboard(get_board_path(args.board))
    def mutator(data):
        require_active(data)
        tasks = data.get("tasks", {})
        if args.id not in tasks:
            raise ValueError(f"Task {args.id} does not exist.")
        t = tasks[args.id]
        if t.get("status") == "blocked":
            raise RuntimeError(f"Cannot start task {args.id}: task is blocked by {t.get('blocked_by')}.")
        if t.get("status") != "pending":
            raise ValueError("Only pending tasks can be claimed.")
        # Check dependencies
        for d in t.get("deps", []):
            dep_status = tasks.get(d, {}).get("status")
            if dep_status in ("failed", "blocked"):
                raise RuntimeError(f"Cannot start task {args.id}: dependency {d} {dep_status}.")
            if dep_status != "completed":
                raise RuntimeError(f"Cannot start task {args.id}: dependency {d} not completed (current: {dep_status}).")
        t["lease_id"] = str(uuid.uuid4())
        t["status"] = "in_progress"
        t["owner"] = args.owner or t.get("owner")
        t["started_at"] = time.time()
        t["last_heartbeat_at"] = time.time()
        data["updated_at"] = time.time()
        return data
    updated = board.update(mutator)
    print(json.dumps({"success": True, "task_id": args.id, "status": "in_progress", "lease_id": updated["tasks"][args.id]["lease_id"]}))

def cmd_heartbeat(args):
    board = AtomicBlackboard(get_board_path(args.board))
    def mutator(data):
        require_active(data)
        tasks = data.get("tasks", {})
        if args.id not in tasks:
            raise ValueError(f"Task {args.id} does not exist.")
        t = tasks[args.id]
        require_lease(data, t, args.lease)
        if t.get("status") != "in_progress":
            raise ValueError(f"Cannot heartbeat task {args.id}: status is '{t.get('status')}', not 'in_progress'.")
        t["last_heartbeat_at"] = time.time()
        if args.owner and args.owner != t.get("owner"):
            raise ValueError("Owner does not match task lease.")
        data["updated_at"] = time.time()
        return data
    board.update(mutator)
    print(json.dumps({"success": True, "task_id": args.id, "heartbeat": time.time()}))

def cmd_reclaim_orphans(args):
    """
    Detect crashed or stalled tasks whose heartbeat/start time exceeds timeout.
    Fails or retries them and marks downstream tasks blocked.
    """
    board = AtomicBlackboard(get_board_path(args.board))
    timeout = args.timeout
    now = time.time()
    reclaimed = []

    def mutator(data):
        require_active(data)
        tasks = data.get("tasks", {})
        for tid, t in list(tasks.items()):
            if t.get("status") == "in_progress":
                last_active = t.get("last_heartbeat_at") or t.get("started_at") or 0
                elapsed = now - last_active
                if elapsed > timeout:
                    t["lease_id"] = None
                    if args.retry and t.get("retry_count", 0) < 2:
                        t["status"] = "pending"
                        t["retry_count"] = t.get("retry_count", 0) + 1
                        t["started_at"] = None
                        t["last_heartbeat_at"] = None
                        reclaimed.append({"id": tid, "action": "retried", "elapsed": elapsed})
                        data.setdefault("signals", []).append({
                            "type": "WARN",
                            "sender": "supervisor",
                            "message": f"Task {tid} stalled for {elapsed:.1f}s; reset to pending (retry #{t['retry_count']})",
                            "timestamp": now
                        })
                    else:
                        t["status"] = "failed"
                        t["completed_at"] = now
                        err_msg = f"Task timed out after {elapsed:.1f}s without heartbeat (worker crashed/abandoned)"
                        t["error"] = err_msg
                        _propagate_blocked(tasks, tid)
                        reclaimed.append({"id": tid, "action": "failed", "elapsed": elapsed})
                        data.setdefault("signals", []).append({
                            "type": "FATAL_BLOCKER",
                            "sender": "supervisor",
                            "message": f"Task {tid} failed: {err_msg}",
                            "timestamp": now
                        })
        data["updated_at"] = now
        return data

    board.update(mutator)
    print(json.dumps({
        "success": True,
        "timeout": timeout,
        "reclaimed_count": len(reclaimed),
        "reclaimed": reclaimed
    }, indent=2, ensure_ascii=False))

def cmd_complete_task(args):
    board = AtomicBlackboard(get_board_path(args.board))
    def mutator(data):
        require_active(data)
        tasks = data.get("tasks", {})
        if args.id not in tasks:
            raise ValueError(f"Task {args.id} does not exist.")
        t = tasks[args.id]
        require_lease(data, t, args.lease)
        t["status"] = "completed"
        t["completed_at"] = time.time()
        t["output"] = args.output
        data["updated_at"] = time.time()
        return data
    board.update(mutator)
    print(json.dumps({"success": True, "task_id": args.id, "status": "completed"}))

def cmd_fail_task(args):
    board = AtomicBlackboard(get_board_path(args.board))
    def mutator(data):
        require_active(data)
        tasks = data.get("tasks", {})
        if args.id not in tasks:
            raise ValueError(f"Task {args.id} does not exist.")
        t = tasks[args.id]
        require_lease(data, t, args.lease)
        t["status"] = "failed"
        t["completed_at"] = time.time()
        t["error"] = args.error
        
        # Propagate blocked status to all dependent tasks
        _propagate_blocked(tasks, args.id)

        # Broadcast blocker signal
        data.setdefault("signals", []).append({
            "type": "FATAL_BLOCKER",
            "sender": t.get("owner", "unknown"),
            "message": f"Task {args.id} failed: {args.error}",
            "timestamp": time.time()
        })
        data["updated_at"] = time.time()
        return data
    board.update(mutator)
    print(json.dumps({"success": True, "task_id": args.id, "status": "failed"}))

def cmd_post_fact(args):
    board = AtomicBlackboard(get_board_path(args.board))
    def mutator(data):
        facts = data.setdefault("shared_facts", {})
        facts[args.key] = {
            "value": args.val,
            "posted_by": args.sender,
            "timestamp": time.time()
        }
        data["updated_at"] = time.time()
        return data
    board.update(mutator)
    print(json.dumps({"success": True, "key": args.key, "value": args.val}))

def cmd_get_fact(args):
    board = AtomicBlackboard(get_board_path(args.board))
    data = board.read()
    facts = data.get("shared_facts", {})
    if args.key in facts:
        print(json.dumps({"success": True, "key": args.key, "fact": facts[args.key]}))
    else:
        print(json.dumps({"success": False, "error": f"Fact key '{args.key}' not found"}))
        sys.exit(1)

def cmd_list_facts(args):
    board = AtomicBlackboard(get_board_path(args.board))
    data = board.read()
    facts = data.get("shared_facts", {})
    matched = {}
    for k, v in facts.items():
        if args.prefix and not k.startswith(args.prefix):
            continue
        if args.sender and v.get("posted_by") != args.sender:
            continue
        matched[k] = v

    if args.json:
        print(json.dumps({"success": True, "count": len(matched), "facts": matched}, indent=2, ensure_ascii=False))
    else:
        print(f"SHARED FACTS ({len(matched)}):")
        for k, v in matched.items():
            print(f"  * {k} = {v.get('value')} (posted by {v.get('posted_by')})")

def cmd_signal(args):
    board = AtomicBlackboard(get_board_path(args.board))
    def mutator(data):
        signals = data.setdefault("signals", [])
        signals.append({
            "type": args.type.upper(),
            "sender": args.sender,
            "message": args.msg,
            "timestamp": time.time()
        })
        data["updated_at"] = time.time()
        return data
    board.update(mutator)
    print(json.dumps({"success": True, "type": args.type.upper(), "message": args.msg}))

def cmd_check_signals(args):
    board = AtomicBlackboard(get_board_path(args.board))
    data = board.read()
    signals = data.get("signals", [])
    blockers = [s for s in signals if s.get("type") in ("FATAL_BLOCKER", "BLOCKER", "ABORT")]
    has_blockers = len(blockers) > 0
    print(json.dumps({
        "success": True,
        "total_signals": len(signals),
        "has_blockers": has_blockers,
        "blockers": blockers,
        "all_signals": signals
    }, indent=2, ensure_ascii=False))
    if args.fail_fast and has_blockers:
        sys.exit(2)

def cmd_complete_mission(args):
    board = AtomicBlackboard(get_board_path(args.board))
    def mutator(data):
        require_active(data)
        if any(t.get("status") != "completed" for t in data.get("tasks", {}).values()):
            raise ValueError("Cannot complete mission with unfinished tasks.")
        t = data.get("task", {})
        t["status"] = "completed"
        t["completed_at"] = time.time()
        t["summary"] = args.summary
        data["updated_at"] = time.time()
        return data
    board.update(mutator)
    print(json.dumps({"success": True, "status": "completed", "summary": args.summary}))

def cmd_abort_mission(args):
    board = AtomicBlackboard(get_board_path(args.board))
    def mutator(data):
        t = data.get("task", {})
        t["status"] = "aborted"
        t["completed_at"] = time.time()
        t["abort_reason"] = args.reason
        data.setdefault("signals", []).append({
            "type": "ABORT",
            "sender": "orchestrator",
            "message": f"Mission aborted: {args.reason}",
            "timestamp": time.time()
        })
        data["updated_at"] = time.time()
        return data
    board.update(mutator)
    print(json.dumps({"success": True, "status": "aborted", "reason": args.reason}))

def cmd_export_summary(args):
    board = AtomicBlackboard(get_board_path(args.board))
    data = board.read()
    if not data:
        print("No blackboard data found.")
        return
    t = data.get("task", {})
    tasks = data.get("tasks", {})
    facts = data.get("shared_facts", {})
    signals = data.get("signals", [])

    lines = [
        f"# /boost Mesh Coordination Run Summary",
        f"- **Mission**: {t.get('title')}",
        f"- **Status**: {t.get('status').upper()}",
        f"- **Coordination Mode**: Peer Mesh (Max Hierarchy Depth = 1)",
        f"- **Total Subtasks**: {len(tasks)}",
        f"- **Shared Facts Published**: {len(facts)}",
    ]
    if t.get("summary"):
        lines.append(f"- **Mission Summary**: {t.get('summary')}")
    if t.get("abort_reason"):
        lines.append(f"- **Abort Reason**: {t.get('abort_reason')}")

    lines.append("\n## Subtask Execution Record")
    for tid, tinfo in tasks.items():
        st = tinfo.get("status")
        sym = "✅" if st == "completed" else "❌" if st == "failed" else "⛔" if st == "blocked" else "⏳"
        dur = ""
        if tinfo.get("started_at") and tinfo.get("completed_at"):
            dur = f" ({tinfo['completed_at'] - tinfo['started_at']:.1f}s)"
        lines.append(f"- {sym} **{tid}** [{tinfo.get('owner')}]: {tinfo.get('title')} [{st}]{dur}")
        if tinfo.get("blocked_by"):
            lines.append(f"  - Blocked by: {tinfo.get('blocked_by')}")
        if tinfo.get("output"):
            lines.append(f"  - Output: {tinfo.get('output')}")
        if tinfo.get("error"):
            lines.append(f"  - Error: {tinfo.get('error')}")

    lines.append("\n## Key Discovered Facts (Shared Memory)")
    if not facts:
        lines.append("- *(No shared facts recorded)*")
    else:
        for k, v in facts.items():
            lines.append(f"- **{k}**: {v.get('value')} *(by {v.get('posted_by')})*")

    if signals:
        lines.append("\n## Critical Signals & Alerts")
        for s in signals:
            lines.append(f"- `[{s.get('type')}]` {s.get('sender')}: {s.get('message')}")

    summary_text = "\n".join(lines)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as of:
            of.write(summary_text)
        print(f"Summary exported to {args.out}")
    else:
        print(summary_text)

# ----------------- Main Entrypoint -----------------

def main():
    parser = argparse.ArgumentParser(description="Boost Multi-Agent Coordinator CLI")
    parser.add_argument("--board", help="Path to blackboard.json (optional)", default=None)
    subparsers = parser.add_subparsers(dest="command")

    # init
    p_init = subparsers.add_parser("init")
    p_init.add_argument("--task", required=True, help="Task title")
    p_init.add_argument("--budget", type=int, default=30, help="Token budget / max steps")

    # status
    p_status = subparsers.add_parser("status")
    p_status.add_argument("--json", action="store_true", help="Output raw JSON")

    # add-task
    p_add = subparsers.add_parser("add-task")
    p_add.add_argument("--id", required=True, help="Task unique ID")
    p_add.add_argument("--title", required=True, help="Task title")
    p_add.add_argument("--owner", required=True, help="Agent role owner")
    p_add.add_argument("--deps", default="", help="Comma-separated prerequisite task IDs")

    # ready-tasks
    p_ready = subparsers.add_parser("ready-tasks")
    p_ready.add_argument("--json", action="store_true", help="Output raw JSON")

    # start-task
    p_start = subparsers.add_parser("start-task")
    p_start.add_argument("--id", required=True, help="Task ID")
    p_start.add_argument("--owner", default=None, help="Agent role owner")

    # heartbeat
    p_hb = subparsers.add_parser("heartbeat")
    p_hb.add_argument("--id", required=True, help="Task ID")
    p_hb.add_argument("--lease", required=True, help="Lease returned by start-task")
    p_hb.add_argument("--owner", default=None, help="Agent role owner")

    # reclaim-orphans
    p_rec = subparsers.add_parser("reclaim-orphans")
    p_rec.add_argument("--timeout", type=float, default=120.0, help="Heartbeat timeout in seconds")
    p_rec.add_argument("--retry", action="store_true", help="Reset stalled tasks to pending instead of failing")

    # complete-task
    p_comp = subparsers.add_parser("complete-task")
    p_comp.add_argument("--id", required=True, help="Task ID")
    p_comp.add_argument("--lease", required=True, help="Lease returned by start-task")
    p_comp.add_argument("--output", required=True, help="Summary output")

    # fail-task
    p_fail = subparsers.add_parser("fail-task")
    p_fail.add_argument("--id", required=True, help="Task ID")
    p_fail.add_argument("--lease", required=True, help="Lease returned by start-task")
    p_fail.add_argument("--error", required=True, help="Error description")

    # post-fact
    p_fact = subparsers.add_parser("post-fact")
    p_fact.add_argument("--key", required=True, help="Fact key")
    p_fact.add_argument("--val", required=True, help="Fact value string")
    p_fact.add_argument("--sender", default="agent", help="Posting agent")

    # get-fact
    p_gfact = subparsers.add_parser("get-fact")
    p_gfact.add_argument("--key", required=True, help="Fact key")

    # list-facts
    p_lfact = subparsers.add_parser("list-facts")
    p_lfact.add_argument("--prefix", default=None, help="Prefix filter")
    p_lfact.add_argument("--sender", default=None, help="Sender filter")
    p_lfact.add_argument("--json", action="store_true", help="Output JSON")

    # signal
    p_sig = subparsers.add_parser("signal")
    p_sig.add_argument("--type", required=True, help="Signal type (BLOCKER, ALERT, MILESTONE, ABORT)")
    p_sig.add_argument("--msg", required=True, help="Signal message")
    p_sig.add_argument("--sender", default="agent", help="Sending agent")

    # check-signals
    p_csig = subparsers.add_parser("check-signals")
    p_csig.add_argument("--fail-fast", action="store_true", help="Exit with code 2 if blockers exist")

    # complete-mission
    p_cmis = subparsers.add_parser("complete-mission")
    p_cmis.add_argument("--summary", required=True, help="Mission accomplishment summary")

    # abort-mission
    p_amis = subparsers.add_parser("abort-mission")
    p_amis.add_argument("--reason", required=True, help="Mission abort reason")

    # export-summary
    p_exp = subparsers.add_parser("export-summary")
    p_exp.add_argument("--out", default=None, help="Output markdown path")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmds = {
        "init": cmd_init,
        "status": cmd_status,
        "add-task": cmd_add_task,
        "ready-tasks": cmd_ready_tasks,
        "start-task": cmd_start_task,
        "heartbeat": cmd_heartbeat,
        "reclaim-orphans": cmd_reclaim_orphans,
        "complete-task": cmd_complete_task,
        "fail-task": cmd_fail_task,
        "post-fact": cmd_post_fact,
        "get-fact": cmd_get_fact,
        "list-facts": cmd_list_facts,
        "signal": cmd_signal,
        "check-signals": cmd_check_signals,
        "complete-mission": cmd_complete_mission,
        "abort-mission": cmd_abort_mission,
        "export-summary": cmd_export_summary
    }

    try:
        cmds[args.command](args)
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()
