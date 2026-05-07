#!/bin/bash
# Start Wealthfolio Web with n8n using Docker Compose
#
# This script launches the Wealthfolio web server alongside n8n
# from the sibling prodagen_n8n repository.
#
# Services:
#   - Wealthfolio: http://localhost:8080
#   - n8n: http://localhost:5678

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
N8N_DIR="$(cd "$SCRIPT_DIR/../../n8n" 2>/dev/null && pwd)" || {
    echo "Error: n8n directory not found at ../n8n"
    echo "Expected directory structure:"
    echo "  precidix/"
    echo "  ├── wealthfolio/  (this repo)"
    echo "  └── n8n/          (prodagen_n8n repo)"
    exit 1
}

cd "$N8N_DIR"

# Create n8n data volume if it doesn't exist
if ! docker volume inspect n8n_data >/dev/null 2>&1; then
    echo "Creating n8n_data volume..."
    docker volume create n8n_data
fi

# Check if we need to build
if [[ "$1" == "--build" ]]; then
    echo "Building wealthfolio image..."
    docker compose build wealthfolio
fi

# Start services
echo "Starting services..."
docker compose up -d

echo ""
echo "Services started:"
echo "  Wealthfolio: http://localhost:8080"
echo "  n8n:         http://localhost:5678"
echo ""
echo "To view logs:  docker compose -f $N8N_DIR/docker-compose.yml logs -f"
echo "To stop:       docker compose -f $N8N_DIR/docker-compose.yml down"
