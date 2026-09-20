import argparse
import sys

from taskforge import job, utils


def cmd_submit(args) -> int:
    try:
        job_id = job.create_job(args.task_type, args.payload)
        if args.quiet:
            print(job_id)
        else:
            print(f"Job submitted successfully! ID: {job_id[:8]}")
        return 0
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_status(args) -> int:
    try:
        current_job = job.get_job(args.job_id)
    except job.AmbiguousIdentifierError as e:
        print(f"Error: short ID '{args.job_id}' is ambiguous", file=sys.stderr)
        print("It matches multiple jobs in the database:", file=sys.stderr)
        for row in e.matches:
            print(f"  - {row['id']} [{row['type']}]", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not current_job:
        print(f"Error: No job found with ID '{args.job_id}'", file=sys.stderr)
        return 1

    worker_id = current_job["worker_id"]
    worker_display = worker_id[:8] if worker_id else "—"

    print("\n--- Taskforge Job Status ---")
    print(f"ID:          {current_job['id'][:8]}")
    print(f"TYPE:        {current_job['type']}")
    print(f"STATUS:      {current_job['status']}")
    print(f"WORKER ID:   {worker_display}")
    print(f"ATTEMPTS:    {current_job['attempts']}/{current_job['max_attempts']}")
    print(f"FENCE TOKEN: {current_job['fence_token']}")
    print(f"CREATED AT:  {utils.format_date(current_job['created_at'])}")
    print(f"CLAIMED AT:  {utils.format_date(current_job['claimed_at'])}")
    print(f"FINISHED AT: {utils.format_date(current_job['completed_at'])}")

    if current_job["error_message"]:
        print(f"ERROR:       {current_job['error_message']}")
    if current_job["result"]:
        print(f"RESULT:      {current_job['result']}")

    print("-----------------------------\n")
    return 0


def cmd_jobs(args) -> int:
    jobs_list = job.list_jobs(args.status, args.limit)
    if not jobs_list:
        print("No jobs found.")
        return 0

    use_color = utils.color_enabled()
    header_fmt = "{:<10} {:<18} {:<14} {:>10}"
    print(header_fmt.format("ID", "TYPE", "STATUS", "AGE"))
    print("─" * 55)

    for j in jobs_list:
        short_id = str(j["id"])[:8]
        task_type = str(j["type"])[:18]
        colored_status = utils.format_status(str(j["status"]), use_color)
        age = utils.format_date(str(j["created_at"]))

        print(f"{short_id:<10} {task_type:<18} {colored_status} {age:>10}")

    # Summary Footer
    total_jobs = job.count_jobs(args.status)
    showing_jobs = len(jobs_list)

    print("─" * 55)
    print(f"Showing {showing_jobs} of {total_jobs} jobs")
    return 0


def cmd_attempts(args) -> int:
    try:
        current_job = job.get_job(args.job_id)
    except (job.AmbiguousIdentifierError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not current_job:
        print(f"Error: No job found with ID '{args.job_id}'", file=sys.stderr)
        return 1

    attempts = job.get_job_attempts(current_job["id"])
    if not attempts:
        print("No attempts recorded for this job.")
        return 0

    print(f"\n--- Attempts for job {current_job['id'][:8]} ---")
    header = "{:<4} {:<10} {:<12} {:<16} {:<16} {}"
    print(header.format("#", "WORKER", "TOKEN", "STATUS", "STARTED", "ERROR"))
    print("─" * 100)
    for a in attempts:
        print(
            header.format(
                a["attempt_number"],
                str(a["worker_id"])[:8],
                a["fence_token"],
                a["status"],
                utils.format_date(a["started_at"]),
                a["error_message"] or "",
            )
        )
    print()
    return 0


def cmd_worker(_args) -> int:
    from taskforge import worker

    worker.run_worker()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taskforge", description="Taskforge Job Queue"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # submit
    p = subparsers.add_parser("submit", help="Submit a new job to the queue")
    p.add_argument("task_type", help="Type of the task (e.g., resize_image)")
    p.add_argument(
        "payload", help='JSON payload for the task(e.g., \'{"file": "photo.jpg"}\')'
    )
    p.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only print the job ID",
    )
    p.set_defaults(func=cmd_submit)

    # status
    p = subparsers.add_parser("status", help="Check the status of a specific job")
    p.add_argument("job_id", help="The UUID of the job to check")
    p.set_defaults(func=cmd_status)

    # worker
    p = subparsers.add_parser("worker", help="Start a background worker process")
    p.set_defaults(func=cmd_worker)

    # jobs
    p = subparsers.add_parser("jobs", help="List jobs in the queue")
    p.add_argument(
        "-n",
        "--limit",
        type=int,
        default=10,
        help="Maximum number of jobs to display (default: 10)",
    )
    p.add_argument(
        "--status",
        choices=["PENDING", "PROCESSING", "COMPLETED", "FAILED"],
        help="Filter jobs by the execution status",
    )
    p.set_defaults(func=cmd_jobs)

    # attempts
    p = subparsers.add_parser("attempts", help="Show the attempt history for a job")
    p.add_argument("job_id", help="The UUID (or short prefix) of the job")
    p.set_defaults(func=cmd_attempts)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    job.init_system()

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
