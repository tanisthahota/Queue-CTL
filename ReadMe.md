# QueueCTL - Background Job Queue System

A CLI-based job queue system with worker processes, automatic retries with exponential backoff, and Dead Letter Queue (DLQ) support.

## 🎯 Features

- ✅ **Job Enqueuing** — Add background jobs via CLI
- ✅ **Multiple Workers** — Run concurrent worker processes with process locking
- ✅ **Automatic Retries** — Failed jobs retry with exponential backoff
- ✅ **Dead Letter Queue** — Permanently failed jobs moved to DLQ
- ✅ **Persistent Storage** — Jobs persist across restarts (JSON-based)
- ✅ **Graceful Shutdown** — Workers finish current job before stopping
- ✅ **Configuration Management** — Configurable retry count and backoff
- ✅ **Job Status Tracking** — Monitor jobs across all states
- ✅ **DLQ Management** — View and retry failed jobs

## 📋 Job States

| State | Description |
|-------|-------------|
| `pending` | Waiting to be picked up by a worker |
| `processing` | Currently being executed |
| `completed` | Successfully executed |
| `failed` | Failed but retryable |
| `dead` | Permanently failed (in DLQ) |

## 🚀 Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/Queue-CTL.git
cd Queue-CTL

# Install dependencies
pip install -r requirements.txt

# Install queuectl as a command
pip install -e .
```

### Basic Usage

```bash
# Enqueue a job
queuectl enqueue '{"id":"job1","command":"echo Hello World"}'

# Start 3 workers
queuectl worker start --count 3

# Check status
queuectl status

# List pending jobs
queuectl list --state pending

# View Dead Letter Queue
queuectl dlq list

# Retry a failed job
queuectl dlq retry job1
```

## 📖 CLI Commands

### Enqueue Jobs

```bash
# Basic job
queuectl enqueue '{"id":"job1","command":"echo hello"}'

# Job with custom retry count
queuectl enqueue '{"id":"job2","command":"sleep 2","max_retries":5}'

# Complex command
queuectl enqueue '{"id":"job3","command":"python script.py --arg value"}'
```

### Worker Management

```bash
# Start a single worker
queuectl worker start

# Start 5 workers
queuectl worker start --count 5

# Stop workers (Ctrl+C for graceful shutdown)
```

### Status & Monitoring

```bash
# Show overall status
queuectl status

# List all jobs
queuectl list

# List pending jobs
queuectl list --state pending

# List completed jobs (limit 20)
queuectl list --state completed --limit 20

# List processing jobs
queuectl list --state processing

# List failed jobs
queuectl list --state failed
```

### Dead Letter Queue (DLQ)

```bash
# List all DLQ jobs
queuectl dlq list

# List first 20 DLQ jobs
queuectl dlq list --limit 20

# Retry a specific job
queuectl dlq retry job1
```

### Configuration

```bash
# Show current configuration
queuectl config show

# Set max retries
queuectl config set max-retries 5

# Set backoff base (exponential backoff: delay = base ^ attempts)
queuectl config set backoff-base 3.0

# Set max backoff delay (in seconds)
queuectl config set backoff-max-delay 7200
```

## 🏗️ Architecture

### Data Flow

```
┌─────────────┐
│   Enqueue   │ → Job added to queue (pending state)
└─────────────┘
       ↓
┌─────────────────────┐
│  Worker Process     │ → Acquires lock, marks as processing
└─────────────────────┘
       ↓
┌──────────────────────────────┐
│  Execute Command             │ → Runs shell command
└──────────────────────────────┘
       ↓
    ┌──────────────────────────────────────────┐
    │         Exit Code Check                  │
    └──────────────────────────────────────────┘
       ↓                                    ↓
   SUCCESS                              FAILURE
       ↓                                    ↓
   COMPLETED                         attempts < max_retries?
       ↓                                    ↓
   Job Finished                    YES ↙      ↘ NO
                                    ↓          ↓
                              Schedule Retry  Move to DLQ
                              (exponential    (dead state)
                               backoff)
```

### Retry Logic

Failed jobs retry with **exponential backoff**:

```
delay = backoff_base ^ (attempts - 1)

Example (backoff_base = 2.0):
- Attempt 1 fails: retry after 2^0 = 1 second
- Attempt 2 fails: retry after 2^1 = 2 seconds
- Attempt 3 fails: retry after 2^2 = 4 seconds
- Attempt 4 fails: moved to DLQ (if max_retries = 3)
```

### Storage Structure

```
.queuectl/
├── jobs.json          # Main job queue
├── dlq.json           # Dead Letter Queue
├── config.json        # Configuration
└── locks/             # Process locks (prevents duplicate execution)
    ├── job1.lock
    ├── job2.lock
    └── ...
```

### Process Locking

- Each job uses a **file-based lock** in `.queuectl/locks/`
- Only one worker can acquire a lock for a job
- Prevents duplicate processing across multiple workers
- Locks are released after job execution completes

## 🧪 Testing

### Run Test Suite

```bash
python test_queuectl.py
```

### Manual Test Scenarios

#### Scenario 1: Basic Job Success

```bash
# Terminal 1: Start workers
queuectl worker start --count 2

# Terminal 2: Enqueue a simple job
queuectl enqueue '{"id":"test1","command":"echo Success"}'

# Check status
queuectl status
# Expected: 1 completed job
```

#### Scenario 2: Job Failure & Retry

```bash
# Enqueue a failing job
queuectl enqueue '{"id":"test2","command":"exit 1","max_retries":3}'

# Watch it retry
queuectl list --state pending
# Expected: Job retries 3 times, then moves to DLQ
```

#### Scenario 3: Multiple Workers

```bash
# Enqueue 10 jobs
for i in {1..10}; do
  queuectl enqueue "{\"id\":\"job$i\",\"command\":\"sleep 1\"}"
done

# Start 3 workers
queuectl worker start --count 3

# Monitor progress
queuectl status
# Expected: Jobs processed in parallel
```

#### Scenario 4: Persistence

```bash
# Enqueue jobs
queuectl enqueue '{"id":"persist1","command":"sleep 10"}'

# Start workers
queuectl worker start --count 1

# Kill workers (Ctrl+C)
# Restart workers
queuectl worker start --count 1

# Check status
queuectl status
# Expected: Jobs still in queue, resume processing
```

#### Scenario 5: DLQ Management

```bash
# Enqueue a job that will fail
queuectl enqueue '{"id":"dlq_test","command":"false","max_retries":1}'

# Wait for it to fail
queuectl worker start --count 1

# View DLQ
queuectl dlq list

# Retry the job
queuectl dlq retry dlq_test

# Check it's back in queue
queuectl list --state pending
```

## 🔧 Configuration

Default configuration (`.queuectl/config.json`):

```json
{
  "max_retries": 3,
  "backoff_base": 2.0,
  "backoff_max_delay": 3600
}
```

### Configuration Options

- **max_retries** — Number of retry attempts before moving to DLQ (default: 3)
- **backoff_base** — Base for exponential backoff calculation (default: 2.0)
- **backoff_max_delay** — Maximum delay between retries in seconds (default: 3600)

## 📊 Job Specification

```json
{
  "id": "unique-job-id",
  "command": "shell command to execute",
  "state": "pending",
  "attempts": 0,
  "max_retries": 3,
  "created_at": "2025-11-04T10:30:00Z",
  "updated_at": "2025-11-04T10:30:00Z",
  "next_retry_at": null,
  "error_message": null
}
```

### Job Fields

- **id** — Unique identifier (required)
- **command** — Shell command to execute (required)
- **state** — Current state (pending, processing, completed, failed, dead)
- **attempts** — Number of execution attempts
- **max_retries** — Maximum retry attempts (default: 3)
- **created_at** — Job creation timestamp
- **updated_at** — Last update timestamp
- **next_retry_at** — Scheduled retry time (for exponential backoff)
- **error_message** — Last error message (if failed)

## 🛠️ Development

### Project Structure

```
Queue-CTL/
├── queuectl/
│   ├── __init__.py        # Package initialization
│   ├── __main__.py        # CLI entry point
│   ├── cli.py             # CLI commands
│   ├── models.py          # Data models (Job, Config)
│   ├── storage.py         # Persistent storage layer
│   ├── queue.py           # Job queue management
│   └── worker.py          # Worker process logic
├── setup.py               # Package setup
├── requirements.txt       # Dependencies
├── test_queuectl.py       # Test suite
└── ReadMe.md              # This file
```

### Key Components

#### `models.py`
- `Job` — Job data model with validation
- `JobState` — Enum for job states
- `Config` — Configuration model

#### `storage.py`
- `Storage` — File-based persistence with JSON
- File locking for concurrent access
- Atomic writes for data consistency

#### `queue.py`
- `JobQueue` — Job queue operations
- State transitions and retry scheduling
- Exponential backoff calculation

#### `worker.py`
- `Worker` — Executes jobs from queue
- Command execution with timeout
- Graceful shutdown handling

#### `cli.py`
- All CLI commands
- Click framework for user interface
- Command validation and error handling

## 🚨 Error Handling

### Common Issues

**Issue: "Job not found in Dead Letter Queue"**
- Solution: Check job ID spelling, use `queuectl dlq list` to see available jobs

**Issue: Workers not processing jobs**
- Solution: Check if workers are running, verify job state with `queuectl status`

**Issue: Jobs stuck in processing state**
- Solution: Worker may have crashed; restart workers and check `.queuectl/locks/`

**Issue: Command not found**
- Solution: Ensure command is available in system PATH, use full paths for scripts

## 📈 Performance Considerations

- **Worker Count** — Adjust based on CPU cores and job I/O characteristics
- **Poll Interval** — Default 1 second; adjust for latency vs. CPU usage trade-off
- **Job Timeout** — Default 5 minutes; configurable per job
- **Storage** — JSON-based; suitable for thousands of jobs; consider SQLite for millions

## 🔐 Security Notes

- Commands are executed with shell=True; validate/sanitize user input
- File permissions on `.queuectl/` should be restricted
- No built-in authentication; add if exposing via API

## 📝 Assumptions & Trade-offs

### Assumptions

1. **Single Machine** — Designed for single-machine deployment; not distributed
2. **Shell Commands** — Jobs are shell commands; not arbitrary code execution
3. **File-Based Storage** — JSON files; not optimized for massive scale
4. **Process-Based Workers** — Uses multiprocessing; not async/threading

### Trade-offs

1. **Simplicity vs. Scale** — Chose simplicity; file-based storage works well up to ~10k jobs
2. **Persistence vs. Speed** — Atomic writes ensure data safety; slightly slower than in-memory
3. **Locking Mechanism** — File-based locks are simple but less efficient than database locks
4. **Worker Model** — Processes are heavier than threads but safer for long-running jobs

## 🎓 Learning Resources

- [Click Documentation](https://click.palletsprojects.com/)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [Python subprocess](https://docs.python.org/3/library/subprocess.html)
- [File Locking in Python](https://docs.python.org/3/library/fcntl.html)

## 📄 License

MIT License - See LICENSE file for details

## 👤 Author

Tanistha Hota

---

**Last Updated:** November 2025
