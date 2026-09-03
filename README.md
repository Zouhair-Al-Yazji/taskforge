# Task Queue

## Problem

What problem am I solving?

- Offloading non-critical tasks: Processes that do not need to happen synchronously like sending verification emails can be moved out of the request-response lifecycle to keep the application responsive.

- Error handling and reliability: Background systems allow for automated retry mechanisms (like exponential backoff) if an external service, such as an email provider, fails.

## What is a job?

Discrete unit of work that is executed outside of the main **request-response** lifecycle.

Instead of making a user wait for a process to finish while they are interacting with an application, the server offloads that piece of work to be processed independently. Key characteristics of a "job" in this context include:

- **Non-synchronous execution**: The job does not need to finish immediately for the user to receive a response from the server.
- **Encapsulated logic**: It represents a specific function or workflow, such as sending a verification email, resizing an uploaded image, or generating a PDF report.
- **Serialized data**: To be queued, the job's requirements (like user IDs or file paths) are packaged into a format, often JSON, so it can be passed to a worker process.
- **Independent processing**: The job is picked up and executed by a worker or consumer running in a separate process, ensuring the main application remains responsive to user traffic.

### Types of Background Tasks

- **One-off tasks**: Single triggers like password reset emails.
- **Recurring tasks**: Scheduled maintenance or report generation.
- **Chain tasks**: Parent-child workflows where one task depends on another, such as video encoding followed by thumbnail generation.
- **Batch tasks**: Triggering many operations simultaneously, like deleting user account data.

## What can a job do?

A job is ideal for any non-critical or time-consuming operation that doesn't need to block your CLI or API response. examples include:

- **Data Processing**: Resizing images or encoding videos.
- **External Service Calls**: Sending emails, push notifications, or making slow API requests.
- **Maintenance**: Cleaning up temporary files, deleting database records, or purging old sessions.
- **Reporting**: Generating PDFs or large data exports on a schedule.

## How does a user submit a job?

Users submit jobs via the CLI interface. Submission generates a unique task record, serializes its arguments, writes it to the queue store, and exits immediately with a tracking ID.

### CLI Interface Specification

```bash
# Submit a new job
$ taskforge submit <task_type> [payload_json_or_args]
# Output: Created job 12345 (Status: pending)

# Inspect job state
$ taskforge status <job_id>

# View job listing
$ taskforge jobs [--status pending|processing|completed|failed]

# Manage worker nodes
$ taskforge worker start [--concurrency 2]
```

## Job lifecycle

1. **PENDING**: Job created via cli and written to persistent storage.
2. **PROCESSING**: A worker claims the job, marks it busy, and assign its PID.
3. **COMPLETED**: The task finishes successfully, execution timing and outputs are saved.
4. **FAILED**: Task thrown an unhandled exception, if retries remains, state reverts to **PENDING** with a backoff delay, otherwise marked permanently **FAILED**

## Components

What components do I think the system needs?

1. **Producer (CLI)**: Validates input parameters, constructs job payloads, generates UUIDs, and writes them to storage.
2. **Broker / Persistent Storage**: A centralized storage layer (SQLite database or lock-protected JSON file) acting as the queue, holding state across system restarts.
3. **Worker (Consumer)**: A long-running process loop that periodically polls the store for PENDING tasks, claims them using state locking, executes the logic, and records output/errors.

## Best Practices & Design Considerations

- **Idempotency**: Ensure tasks can be executed multiple times without side effects if retried.
- **Monitoring & Alerting**: Track queue length, worker health, and error rates using tools like Prometheus and Grafana.
- **Keep tasks small**: Avoid long-running tasks; break them into smaller, focused units.

## First milestone

What is the smallest version I can build?

V1 Flow: submit task -> write JSON -> worker polls JSON -> executes -> updates JSON
