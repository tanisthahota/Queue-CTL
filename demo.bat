@echo off
REM QueueCTL Demo Script for Windows
REM This script demonstrates the core functionality of QueueCTL

setlocal enabledelayedexpansion

echo.
echo ==========================================
echo QueueCTL - Background Job Queue Demo
echo ==========================================
echo.

REM Clean up previous demo data
echo 🧹 Cleaning up previous demo data...
if exist .queuectl (
    rmdir /s /q .queuectl
)
echo.

REM Show initial status
echo 📊 Initial Status:
python -m queuectl status
echo.

REM Enqueue some jobs
echo 📝 Enqueuing jobs...
python -m queuectl enqueue "{\"id\":\"demo1\",\"command\":\"echo Job 1: Success\",\"max_retries\":3}"
python -m queuectl enqueue "{\"id\":\"demo2\",\"command\":\"echo Job 2: Success\",\"max_retries\":3}"
python -m queuectl enqueue "{\"id\":\"demo3\",\"command\":\"exit 1\",\"max_retries\":2}"
python -m queuectl enqueue "{\"id\":\"demo4\",\"command\":\"timeout /t 1 && echo Job 4: Success\",\"max_retries\":3}"
python -m queuectl enqueue "{\"id\":\"demo5\",\"command\":\"exit 1\",\"max_retries\":1}"
echo ✓ Enqueued 5 jobs
echo.

REM Show pending jobs
echo 📋 Pending Jobs:
python -m queuectl list --state pending
echo.

REM Show configuration
echo ⚙️  Current Configuration:
python -m queuectl config show
echo.

REM Start workers in background
echo 🚀 Starting 2 workers...
start "QueueCTL Workers" python -m queuectl worker start --count 2
echo ✓ Workers started
echo.

REM Wait for jobs to process
echo ⏳ Waiting for jobs to process (10 seconds)...
timeout /t 10 /nobreak
echo.

REM Show status
echo 📊 Status After Processing:
python -m queuectl status
echo.

REM Show completed jobs
echo ✅ Completed Jobs:
python -m queuectl list --state completed --limit 10
echo.

REM Show failed jobs
echo ❌ Failed Jobs:
python -m queuectl list --state failed --limit 10
echo.

REM Show DLQ
echo 💀 Dead Letter Queue:
python -m queuectl dlq list
echo.

REM Retry a DLQ job
echo 🔄 Retrying a job from DLQ...
python -m queuectl dlq retry demo5
echo ✓ Job demo5 moved back to queue
echo.

REM Show updated status
echo 📊 Final Status:
python -m queuectl status
echo.

REM Show final job list
echo 📋 Final Job List:
python -m queuectl list --limit 10
echo.

echo ==========================================
echo ✓ Demo Complete!
echo ==========================================
echo.

endlocal
