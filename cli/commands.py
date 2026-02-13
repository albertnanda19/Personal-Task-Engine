"""CLI commands and argument parsing."""

from __future__ import annotations

import argparse
from typing import Any

from bot.discord_client import send_message
from services.scoring_service import recalculate_all_scores
from services.summary_service import get_dashboard_summary, get_weekly_report
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
    _add_task_focus(task_subparsers)
    _add_task_recalculate_score(task_subparsers)
    _add_task_summary(task_subparsers)
    _add_task_weekly_report(task_subparsers)
    _add_task_send_summary(task_subparsers)
    _add_task_send_focus(task_subparsers)
    _add_task_send_weekly(task_subparsers)

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


def _add_task_focus(task_subparsers: argparse._SubParsersAction) -> None:
    p = task_subparsers.add_parser("focus", help="Show top 3 tasks by execution score")
    p.set_defaults(func=_cmd_task_focus)


def _add_task_recalculate_score(task_subparsers: argparse._SubParsersAction) -> None:
    p = task_subparsers.add_parser(
        "recalculate-score", help="Recalculate execution score for all tasks"
    )
    p.set_defaults(func=_cmd_task_recalculate_score)


def _add_task_summary(task_subparsers: argparse._SubParsersAction) -> None:
    p = task_subparsers.add_parser("summary", help="Show productivity dashboard")
    p.set_defaults(func=_cmd_task_summary)


def _add_task_weekly_report(task_subparsers: argparse._SubParsersAction) -> None:
    p = task_subparsers.add_parser(
        "weekly-report", help="Show weekly performance report (last 7 days)"
    )
    p.set_defaults(func=_cmd_task_weekly_report)


def _add_task_send_summary(task_subparsers: argparse._SubParsersAction) -> None:
    p = task_subparsers.add_parser(
        "send-summary", help="Send dashboard summary to Discord"
    )
    p.set_defaults(func=_cmd_task_send_summary)


def _add_task_send_focus(task_subparsers: argparse._SubParsersAction) -> None:
    p = task_subparsers.add_parser(
        "send-focus", help="Send focus (top 3 tasks) to Discord"
    )
    p.set_defaults(func=_cmd_task_send_focus)


def _add_task_send_weekly(task_subparsers: argparse._SubParsersAction) -> None:
    p = task_subparsers.add_parser(
        "send-weekly", help="Send weekly performance report to Discord"
    )
    p.set_defaults(func=_cmd_task_send_weekly)


def _format_dashboard_message(summary: dict[str, Any]) -> str:
    avg = float(summary.get("average_execution_score") or 0)
    lines = [
        "PERSONAL TASK DASHBOARD",
        "-----------------------",
        f"Todo: {summary.get('total_todo', 0)}",
        f"Doing: {summary.get('total_doing', 0)}",
        f"Done: {summary.get('total_done', 0)}",
        f"Overdue: {summary.get('total_overdue', 0)}",
        f"Average Score: {avg:.1f}",
    ]
    return "\n".join(lines)


def _format_focus_message(tasks: list[dict[str, Any]]) -> str:
    lines = ["FOCUS TODAY", "-----------"]
    if not tasks:
        lines.append("(none)")
        return "\n".join(lines)

    for idx, t in enumerate(tasks, start=1):
        score = float(t.get("execution_score") or 0)
        due = t.get("due_date") or "-"
        lines.append(
            f"{idx}. [ID {t['id']}] {t['title_generated']} Score: {score:.0f} Due: {due}"
        )
    return "\n".join(lines)


def _format_weekly_message(report: dict[str, Any]) -> str:
    avg_days = float(report.get("average_completion_time_days") or 0)
    most_common_priority = report.get("most_common_priority")
    most_common_type = report.get("most_common_type")

    lines = [
        "WEEKLY PERFORMANCE REPORT",
        "-------------------------",
        f"Tasks Completed (7d): {report.get('tasks_completed_7d', 0)}",
        f"Story Points Completed: {report.get('story_points_completed_7d', 0)}",
        f"Average Completion Time: {avg_days:.1f} days",
        f"Most Common Priority: {most_common_priority.title() if most_common_priority else '-'}",
        f"Most Common Type: {most_common_type.title() if most_common_type else '-'}",
    ]
    return "\n".join(lines)


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


def _cmd_task_focus(args: argparse.Namespace) -> int:
    tasks = list_tasks()
    tasks = [t for t in tasks if str(t.get("status") or "").lower() != "done"]
    tasks.sort(key=lambda t: float(t.get("execution_score") or 0), reverse=True)
    top = tasks[:3]

    if not top:
        print("No tasks found.")
        return 0

    for t in top:
        due = t.get("due_date") or "-"
        score = float(t.get("execution_score") or 0)
        print(
            f"{t['id']}\t{t['title_generated']}\t{t['status']}\t{due}\t{score}"
        )

    return 0


def _cmd_task_recalculate_score(args: argparse.Namespace) -> int:
    updated = recalculate_all_scores()
    print(f"Recalculated execution_score for {updated} tasks.")
    return 0


def _cmd_task_summary(args: argparse.Namespace) -> int:
    summary = get_dashboard_summary()

    print("PERSONAL TASK DASHBOARD")
    print("-----------------------")
    print("")

    print(f"Total tasks: {summary['total_tasks']}")
    print(f"Todo: {summary['total_todo']}")
    print(f"Doing: {summary['total_doing']}")
    print(f"Done: {summary['total_done']}")
    print(f"Overdue: {summary['total_overdue']}")
    print(f"Average Execution Score: {summary['average_execution_score']:.1f}")
    print("")

    print("Top 3 Focus:")
    top_3 = summary.get("top_3") or []
    if not top_3:
        print("(none)")
    else:
        for idx, t in enumerate(top_3, start=1):
            score = float(t.get("execution_score") or 0)
            print(f"{idx}. [ID {t['id']}] {t['title_generated']} Score: {score:.0f}")

    print("")
    print("Oldest Todo:")
    oldest = summary.get("oldest_todo")
    if not oldest:
        print("(none)")
    else:
        created_at = oldest.get("created_at") or "-"
        print(f"[ID {oldest['id']}] {oldest['title_generated']} Created at: {created_at}")

    return 0


def _cmd_task_weekly_report(args: argparse.Namespace) -> int:
    report = get_weekly_report()

    print("WEEKLY PERFORMANCE REPORT")
    print("-------------------------")
    print("")

    print(f"Tasks Completed (7d): {report['tasks_completed_7d']}")
    print(f"Story Points Completed: {report['story_points_completed_7d']}")
    print(f"Average Completion Time: {report['average_completion_time_days']:.1f} days")

    most_common_priority = report.get("most_common_priority")
    most_common_type = report.get("most_common_type")
    print(f"Most Common Priority: {most_common_priority.title() if most_common_priority else '-'}")
    print(f"Most Common Type: {most_common_type.title() if most_common_type else '-'}")

    return 0


def _cmd_task_send_summary(args: argparse.Namespace) -> int:
    summary = get_dashboard_summary()
    message = _format_dashboard_message(summary)
    ok = send_message(message)
    print("Sent." if ok else "Failed to send.")
    return 0 if ok else 1


def _cmd_task_send_focus(args: argparse.Namespace) -> int:
    tasks = list_tasks()
    tasks = [t for t in tasks if str(t.get("status") or "").lower() != "done"]
    tasks.sort(key=lambda t: float(t.get("execution_score") or 0), reverse=True)
    top = tasks[:3]
    message = _format_focus_message(top)
    ok = send_message(message)
    print("Sent." if ok else "Failed to send.")
    return 0 if ok else 1


def _cmd_task_send_weekly(args: argparse.Namespace) -> int:
    report = get_weekly_report()
    message = _format_weekly_message(report)
    ok = send_message(message)
    print("Sent." if ok else "Failed to send.")
    return 0 if ok else 1
