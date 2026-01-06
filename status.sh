#!/bin/bash

# Status script for Batocera Games Catalog
# Shows the status of all services

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.services.pid"

# Function to check if a port is in use
check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1 ; then
        local pid=$(lsof -ti :$port)
        echo "$pid"
        return 0
    else
        return 1
    fi
}

# Function to check process status
check_process() {
    local pid=$1
    if kill -0 $pid 2>/dev/null; then
        local cmd=$(ps -p $pid -o comm= 2>/dev/null)
        echo "✓ Running (PID: $pid, Command: $cmd)"
        return 0
    else
        echo "✗ Not running"
        return 1
    fi
}

echo "========================================="
echo "Batocera Games Catalog Services Status"
echo "========================================="
echo ""

# Check backend
echo "Backend (Port 8000):"
backend_pid=$(check_port 8000)
if [ -n "$backend_pid" ]; then
    check_process $backend_pid
else
    echo "✗ Not running"
fi
echo ""

# Check frontend
echo "Frontend (Port 3000):"
frontend_pid=$(check_port 3000)
if [ -n "$frontend_pid" ]; then
    check_process $frontend_pid
else
    echo "✗ Not running"
fi
echo ""

# Check PID file
if [ -f "$PID_FILE" ]; then
    echo "Tracked PIDs:"
    while read pid; do
        if [ -n "$pid" ]; then
            echo "  PID $pid: $(check_process $pid 2>&1 | grep -o 'Running\|Not running')"
        fi
    done < "$PID_FILE"
    echo ""
fi

# Summary
backend_running=$(check_port 8000 >/dev/null 2>&1 && echo "yes" || echo "no")
frontend_running=$(check_port 3000 >/dev/null 2>&1 && echo "yes" || echo "no")

echo "Summary:"
if [ "$backend_running" = "yes" ] && [ "$frontend_running" = "yes" ]; then
    echo "✓ All services are running"
    echo ""
    echo "Backend:  http://localhost:8000"
    echo "Frontend: http://localhost:3000"
elif [ "$backend_running" = "yes" ] || [ "$frontend_running" = "yes" ]; then
    echo "⚠ Some services are running"
else
    echo "✗ No services are running"
fi
echo ""



