#!/bin/bash

# Stop script for Batocera Games Catalog
# Stops all running services

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.services.pid"

# Function to kill process by PID
kill_process() {
    local pid=$1
    if kill -0 $pid 2>/dev/null; then
        echo "Stopping process $pid..."
        kill $pid 2>/dev/null
        # Wait a bit for graceful shutdown
        sleep 1
        # Force kill if still running
        if kill -0 $pid 2>/dev/null; then
            echo "Force killing process $pid..."
            kill -9 $pid 2>/dev/null
        fi
        return 0
    else
        echo "Process $pid is not running"
        return 1
    fi
}

# Function to kill processes by port
kill_by_port() {
    local port=$1
    local pids=$(lsof -ti :$port 2>/dev/null)
    if [ -n "$pids" ]; then
        echo "Stopping processes on port $port..."
        for pid in $pids; do
            kill_process $pid
        done
    fi
}

echo "========================================="
echo "Stopping Batocera Games Catalog Services"
echo "========================================="

# Stop processes from PID file
if [ -f "$PID_FILE" ]; then
    echo "Stopping processes from PID file..."
    while read pid; do
        if [ -n "$pid" ]; then
            kill_process $pid
        fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
fi

# Also kill any processes on our ports (in case PID file is missing)
echo "Checking for processes on ports 8000 and 3000..."
kill_by_port 8000
kill_by_port 3000

# Kill any remaining uvicorn processes
echo "Checking for remaining uvicorn processes..."
pkill -f "uvicorn app.main:app" 2>/dev/null

# Kill any remaining npm/vite processes
echo "Checking for remaining npm/vite processes..."
pkill -f "vite" 2>/dev/null

echo ""
echo "All services stopped!"
echo ""


