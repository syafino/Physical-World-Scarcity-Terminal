#!/bin/bash
# PWST Startup Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}"
echo "═══════════════════════════════════════════════════════════════"
echo "  PWST | Physical World Scarcity Terminal"
echo "═══════════════════════════════════════════════════════════════"
echo -e "${NC}"

# Check for .env file
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠ No .env file found. Creating from template...${NC}"
    cp .env.example .env
    echo -e "${YELLOW}  Please edit .env and add your API keys before running again.${NC}"
    echo ""
    echo "  Required:"
    echo "    - EIA_API_KEY (get free key at https://www.eia.gov/opendata/register.php)"
    echo ""
    echo "  Optional:"
    echo "    - MAPBOX_ACCESS_TOKEN (for enhanced maps)"
    echo ""
    exit 1
fi

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${YELLOW}⚠ Docker not found. Please install Docker Desktop.${NC}"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo -e "${YELLOW}⚠ Docker daemon not running. Please start Docker Desktop.${NC}"
    exit 1
fi

# Parse arguments
ACTION="${1:-up}"

case "$ACTION" in
    up)
        echo -e "${BLUE}▶ Starting PWST services...${NC}"
        docker-compose up --build -d
        
        echo ""
        echo -e "${GREEN}✓ PWST is starting up!${NC}"
        echo ""
        echo "  Terminal UI:  http://localhost:8501"
        echo "  API Docs:     http://localhost:8000/docs"
        echo ""
        echo "  Waiting for services to be healthy..."
        
        # Wait for API to be ready
        for i in {1..30}; do
            if curl -s http://localhost:8000/health > /dev/null 2>&1; then
                echo -e "${GREEN}✓ API is ready!${NC}"
                break
            fi
            sleep 2
            echo "  Waiting... ($i/30)"
        done
        
        echo ""
        echo "  Try these commands in the terminal:"
        echo "    WATR US-TX <GO>"
        echo "    GRID ERCOT <GO>"
        echo ""
        ;;
    
    down)
        echo -e "${BLUE}▶ Stopping PWST services...${NC}"
        docker-compose down
        echo -e "${GREEN}✓ All services stopped.${NC}"
        ;;
    
    logs)
        echo -e "${BLUE}▶ Showing logs (Ctrl+C to exit)...${NC}"
        docker-compose logs -f
        ;;
    
    reset)
        echo -e "${YELLOW}⚠ This will delete all data. Continue? (y/N)${NC}"
        read -r confirm
        if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
            docker-compose down -v
            echo -e "${GREEN}✓ All data cleared.${NC}"
        else
            echo "Cancelled."
        fi
        ;;
    
    ingest)
        echo -e "${BLUE}▶ Triggering manual data ingestion...${NC}"
        docker-compose exec api python -c "
from src.ingestion.usgs import USGSWaterFetcher
from src.ingestion.eia import EIAGridFetcher

print('Fetching USGS water data...')
usgs = USGSWaterFetcher()
usgs.save_to_db(usgs.fetch_texas_groundwater())

print('Fetching EIA grid data...')
eia = EIAGridFetcher()
eia.save_to_db(eia.fetch_ercot_grid())

print('Done!')
"
        ;;
    
    *)
        echo "Usage: $0 {up|down|logs|reset|ingest}"
        echo ""
        echo "Commands:"
        echo "  up      Start all services (default)"
        echo "  down    Stop all services"
        echo "  logs    View service logs"
        echo "  reset   Delete all data and volumes"
        echo "  ingest  Manually trigger data ingestion"
        exit 1
        ;;
esac
