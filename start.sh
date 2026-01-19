#!/bin/bash

# Start script for Batocera Games Catalog
# Starts backend and frontend services

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.services.pid"
LOG_DIR="$SCRIPT_DIR/logs"

# Create logs directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Function to check if a port is in use
check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1 ; then
        return 0  # Port is in use
    else
        return 1  # Port is free
    fi
}

# Function to start backend
start_backend() {
    echo "Starting backend server..."
    
    if check_port 8000; then
        echo "Warning: Port 8000 is already in use. Backend may already be running."
        return 1
    fi
    
    cd "$SCRIPT_DIR/backend"
    
    # Check if virtual environment exists, create if not
    if [ ! -d "venv" ]; then
        echo "Creating virtual environment..."
        python3 -m venv venv
        if [ $? -ne 0 ]; then
            echo "Error: Failed to create virtual environment"
            cd "$SCRIPT_DIR"
            return 1
        fi
    fi
    
    # Check if venv/bin/activate exists
    if [ ! -f "venv/bin/activate" ]; then
        echo "Error: Virtual environment is not properly created"
        echo "Removing broken venv and recreating..."
        rm -rf venv
        python3 -m venv venv
        if [ $? -ne 0 ]; then
            echo "Error: Failed to recreate virtual environment"
            cd "$SCRIPT_DIR"
            return 1
        fi
    fi
    
    # Use the Python from venv directly instead of activating
    VENV_PYTHON="$SCRIPT_DIR/backend/venv/bin/python"
    VENV_PIP="$SCRIPT_DIR/backend/venv/bin/pip"
    
    # Install/upgrade dependencies
    echo "Installing/updating backend dependencies..."
    $VENV_PIP install --upgrade -r requirements.txt > "$LOG_DIR/backend_install.log" 2>&1
    if [ $? -ne 0 ]; then
        echo "Warning: Some dependencies may have failed to install. Check $LOG_DIR/backend_install.log"
    fi
    
    # Get number of workers from environment (default: 4)
    BACKEND_WORKERS=${BACKEND_WORKERS:-4}
    echo "Starting backend with $BACKEND_WORKERS worker(s)..."
    
    # Start backend server using venv python with multiple workers
    nohup $VENV_PYTHON -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers $BACKEND_WORKERS > "$LOG_DIR/backend.log" 2>&1 &
    BACKEND_PID=$!
    echo "Backend started with PID: $BACKEND_PID (workers: $BACKEND_WORKERS)"
    echo "$BACKEND_PID" >> "$PID_FILE"
    
    # Wait a moment to check if it started successfully
    sleep 2
    if ! kill -0 $BACKEND_PID 2>/dev/null; then
        echo "Error: Backend failed to start. Check $LOG_DIR/backend.log for details."
        cd "$SCRIPT_DIR"
        return 1
    fi
    
    cd "$SCRIPT_DIR"
    return 0
}

# Function to start frontend
start_frontend() {
    echo "Starting frontend server..."
    
    if check_port 3000; then
        echo "Warning: Port 3000 is already in use. Frontend may already be running."
        return 1
    fi
    
    cd "$SCRIPT_DIR/frontend"
    
    # Check if node_modules exists
    if [ ! -d "node_modules" ]; then
        echo "Installing frontend dependencies..."
        npm install > "$LOG_DIR/frontend_install.log" 2>&1
    fi
    
    # Start frontend server
    nohup npm run dev > "$LOG_DIR/frontend.log" 2>&1 &
    FRONTEND_PID=$!
    echo "Frontend started with PID: $FRONTEND_PID"
    echo "$FRONTEND_PID" >> "$PID_FILE"
    
    # Wait a moment to check if it started successfully
    sleep 2
    if ! kill -0 $FRONTEND_PID 2>/dev/null; then
        echo "Error: Frontend failed to start. Check $LOG_DIR/frontend.log for details."
        return 1
    fi
    
    cd "$SCRIPT_DIR"
    return 0
}

# Main execution
echo "========================================="
echo "Starting Batocera Games Catalog Services"
echo "========================================="

# Clear old PID file
> "$PID_FILE"

# Start backend
if start_backend; then
    echo "✓ Backend started successfully"
else
    echo "✗ Backend failed to start"
fi

# Start frontend
if start_frontend; then
    echo "✓ Frontend started successfully"
else
    echo "✗ Frontend failed to start"
fi

echo ""
echo "Services started!"
echo "Backend: http://localhost:8000"
echo "Frontend: http://localhost:3000"
echo ""
echo "Logs are available in: $LOG_DIR"
echo "To stop services, run: ./stop.sh"
echo ""

