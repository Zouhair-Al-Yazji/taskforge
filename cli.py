import argparse
import sys

import job
import utils
import worker


def main():
    parser = argparse.ArgumentParser(
        prog="taskforge", description="Taskforge Job Queue"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # command: submit
    submit_parser = subparsers.add_parser(
        "submit", help="Submit a new job to the queue"
    )
    submit_parser.add_argument(
        "task_type", help="Type of the task (e.g., resize_image)"
    )
    submit_parser.add_argument(
        "payload", help='JSON payload for the task(e.g., \'{"file": "photo.jpg"}\')'
    )

    # command: submit
    status_parser = subparsers.add_parser(
        "status", help="Check the status of a specific job"
    )
    status_parser.add_argument("job_id", help="The UUID of the job to check")

    # command: worker
    subparsers.add_parser("worker", help="Start a background worker process")

    # command: jobs
    jobs_parser = subparsers.add_parser("jobs", help="List jobs in the queue")
    jobs_parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=10,
        help="Maximum number of jobs to display (default: 10)",
    )
    jobs_parser.add_argument(
        "--status",
        choices=["PENDING", "PROCESSING", "COMPLETED", "FAILED"],
        help="Filter jobs by the execution status",
    )

    args = parser.parse_args()

    if args.command == "submit":
        try:
            job_id = job.create_job(args.task_type, args.payload)
            print(f"Job submitted successfully! ID: {job_id[:8]}")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    if args.command == "status":
        try:
            current_job = job.get_job(args.job_id)
            if not current_job:
                print(f"Error: No job found with ID '{args.job_id}'", file=sys.stderr)
                sys.exit(1)
            print("\n--- Taskforge Job Status ---")
            print(f"ID:          {current_job['id'][:8]}")
            print(f"TYPE:        {current_job['type']}")
            print(f"STATUS:      {current_job['status']}")
            print(f"CREATED AT:  {current_job['created_at']}")
            print("-----------------------------\n")
        except job.AmbiguousIdentifierError as e:
            print(f"Error: short ID '{args.job_id}' is ambiguous", file=sys.stderr)
            print("It matches multiple jobs in the database", file=sys.stderr)
            for row in e.matches:
                print(f"  - {row['id']} [{row['type']}]", file=sys.stderr)
            sys.exit(1)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    if args.command == "worker":
        worker.run_worker()

    if args.command == "jobs":
        jobs_list = job.list_jobs(args.status, args.limit)
        if not jobs_list:
            print("No jobs found.")
            return

        use_color = sys.stdout.isatty()
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
