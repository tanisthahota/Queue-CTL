#!/bin/bash

# QueueCTL Demo Script
# This script demonstrates the core functionality of QueueCTL

set -e

echo "=========================================="
echo "QueueCTL - Background Job Queue Demo"
echo "=========================================="
echo ""

# Clean up previous demo data
echo "🧹 Cleaning up previous demo data..."
rm -rf .queuectl
echo ""

# Show initial status
echo "📊 Initial Status:"
python -m queuectl status
echo ""

# Enqueue some jobs
echo "📝 Enqueuing jobs..."
python -m queuectl enqueue '{"id":"demo1","command":"echo Job 1: Success","max_retries":3}'
python -m queuectl enqueue '{"id":"demo2","command":"echo Job 2: Success","max_retries":3}'
python -m queuectl enqueue '{"id":"demo3","command":"false","max_retries":2}'
python -m queuectl enqueue '{"id":"demo4","command":"sleep 1 && echo Job 4: Success","max_retries":3}'
python -m queuectl enqueue '{"id":"demo5","command":"exit 1","max_retries":1}'
echo "✓ Enqueued 5 jobs"
echo ""

# Show pending jobs
echo "📋 Pending Jobs:"
python -m queuectl list --state pending
echo ""

# Show configuration
echo "⚙️  Current Configuration:"
python -m queuectl config show
echo ""

# Start workers in background
echo "🚀 Starting 2 workers..."
python -m queuectl worker start --count 2 &
WORKER_PID=$!
echo "✓ Workers started (PID: $WORKER_PID)"
echo ""

# Wait for jobs to process
echo "⏳ Waiting for jobs to process (10 seconds)..."
sleep 10
echo ""

# Show status
echo "📊 Status After Processing:"
python -m queuectl status
echo ""

# Show completed jobs
echo "✅ Completed Jobs:"
python -m queuectl list --state completed --limit 10
echo ""

# Show failed jobs
echo "❌ Failed Jobs:"
python -m queuectl list --state failed --limit 10
echo ""

# Show DLQ
echo "💀 Dead Letter Queue:"
python -m queuectl dlq list
echo ""

# Stop workers
echo "🛑 Stopping workers..."
kill $WORKER_PID 2>/dev/null || true
wait $WORKER_PID 2>/dev/null || true
echo "✓ Workers stopped"
echo ""

# Retry a DLQ job
echo "🔄 Retrying a job from DLQ..."
python -m queuectl dlq retry demo5
echo "✓ Job demo5 moved back to queue"
echo ""

# Show updated status
echo "📊 Final Status:"
python -m queuectl status
echo ""

# Show final job list
echo "📋 Final Job List:"
python -m queuectl list --limit 10
echo ""

echo "=========================================="
echo "✓ Demo Complete!"
echo "=========================================="
