"""CLI commands and argument parsing."""

from __future__ import annotations

import argparse
from typing import Any

from services.task_service import create_task_with_formatting, list_tasks, remove_task, set_task_status


def build_parser() -> argparse.ArgumentParser:
    """Build the root argparse parser."""

    parser = argparse.ArgumentParser(prog="personal_task_engine")
    subparsers = parser.add_subparsers(dest="entity", required=True)

    task_parser = subparsers.add_parser("task", help="Task operations")
    task_subparsers = task_parser.add_subparsers(dest="command", required=True)

    _add_task_add(task_subparsers)
    _add_task_list(task_subparsers)
    _add_task_update_status(task_subparsers)
    _add_task_delete(task_subparsers)

    return parser


def _add_task_add(task_subparsers: argparse._SubParsersAction) -> None:
    p = task_subparsers.add_parser("add", help="Add a new task")

    p.add_argument("--project", required=True)
    p.add_argument("--module", required=True)
    p.add_argument("--layer", required=True)
    p.add_argument("--title", required=True, dest="title_raw")
    p.add_argument("--type", required=True)
    p.add_argument("--priority", required=True)

    p.add_argument("--story_points", type=int)
    p.add_argument("--epic")
    p.add_argument("--description")
    p.add_argument("--start_date")
    p.add_argument("--due_date")
    p.add_argument("--impact_score", type=int)
    p.add_argument("--energy_required", type=int)

    p.set_defaults(func=_cmd_task_add)


def _add_task_list(task_subparsers: argparse._SubParsersAction) -> None:
    p = task_subparsers.add_parser("list", help="List tasks")
    p.add_argument("--status")
    p.set_defaults(func=_cmd_task_list)


def _add_task_update_status(task_subparsers: argparse._SubParsersAction) -> None:
    p = task_subparsers.add_parser("update-status", help="Update a task status")
    p.add_argument("--id", required=True, type=int)
    p.add_argument("--status", required=True)
    p.set_defaults(func=_cmd_task_update_status)


def _add_task_delete(task_subparsers: argparse._SubParsersAction) -> None:
    p = task_subparsers.add_parser("delete", help="Delete a task")
    p.add_argument("--id", required=True, type=int)
    p.set_defaults(func=_cmd_task_delete)


def run_cli(argv: list[str] | None = None) -> int:
    """Run the CLI and return an exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)

    handler = getattr(args, "func", None)
    if handler is None:
        parser.print_help()
        return 2

    return int(handler(args))


def _cmd_task_add(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {
        "project": args.project,
        "module": args.module,
        "layer": args.layer,
        "title_raw": args.title_raw,
        "type": args.type,
        "priority": args.priority,
        "story_points": args.story_points,
        "epic": args.epic,
        "description": args.description,
        "start_date": args.start_date,
        "due_date": args.due_date,
        "impact_score": args.impact_score,
        "energy_required": args.energy_required,
    }

    task_id = create_task_with_formatting(payload)
    print(f"Created task id={task_id}")
    return 0


def _cmd_task_list(args: argparse.Namespace) -> int:
    tasks = list_tasks(status=args.status)

    if not tasks:
        print("No tasks found.")
        return 0

    for t in tasks:
        due = t.get("due_date") or "-"
        print(
            f"{t['id']}\t{t['status']}\t{t['priority']}\t{due}\t{t['title_generated']}"
        )

    return 0


def _cmd_task_update_status(args: argparse.Namespace) -> int:
    updated = set_task_status(task_id=args.id, status=args.status)
    if updated == 0:
        print(f"No task found with id={args.id}")
        return 1

    print(f"Updated task id={args.id} status={args.status}")
    return 0


def _cmd_task_delete(args: argparse.Namespace) -> int:
    deleted = remove_task(task_id=args.id)
    if deleted == 0:
        print(f"No task found with id={args.id}")
        return 1

    print(f"Deleted task id={args.id}")
    return 0
