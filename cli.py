import argparse
import sys

import job


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

    args = parser.parse_args()

    if args.command == "submit":
        try:
            job_id = job.create_job(args.task_type, args.payload)
            print(f"Job submitted successfully! ID: {job_id}")
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
            print(f"ID:          {current_job['id']}")
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
