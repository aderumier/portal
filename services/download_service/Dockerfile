# Use Debian 13 (Testing/Trixie) minimal image
FROM debian:testing-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

# Install Python and system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Create a virtual environment to avoid PEP 668 restricted environment issues
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create volume mount point for ROMs and saves
RUN mkdir -p /userdata/roms /userdata/saves

# Set default environment variables
ENV ROMS_PATH=/userdata/roms
ENV SAVEDIR=/userdata/saves

# Expose P2P port
EXPOSE 8765

# Run the service
CMD ["python", "download_service.py"]
