#!/bin/bash
# Oneiric Development Startup Script
#
# This script provides a convenient way to start Oneiric in different modes.
# Usage: ./dev-start.sh [lite|standard] [options...]
#
# Examples:
#   ./dev-start.sh lite
#   ./dev-start.sh standard --manifest-url https://example.com/manifest.yaml
#   ./dev-start.sh standard --watch

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default mode
MODE=${1:-lite}

# Function to print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if oneiric command is available
if ! command -v oneiric &> /dev/null; then
    print_error "oneiric command not found. Please install oneiric first:"
    echo "  uv add oneiric"
    echo "  or"
    echo "  pip install oneiric"
    exit 1
fi

# Parse mode and shift arguments
case $MODE in
    lite)
        print_info "Starting Oneiric in LITE mode..."
        echo ""
        echo "Configuration:"
        echo "  - Remote resolution: Disabled"
        echo "  - Manifest sync: Manual only"
        echo "  - Signature verification: Optional"
        echo "  - External dependencies: Zero"
        echo ""
        print_warning "Data will not persist across restarts in lite mode!"
        echo ""

        # Start in lite mode
        oneiric start --mode=lite "${@:2}"
        ;;

    standard)
        print_info "Starting Oneiric in STANDARD mode..."
        echo ""
        echo "Configuration:"
        echo "  - Remote resolution: Enabled"
        echo "  - Manifest sync: Automatic"
        echo "  - Signature verification: Required"
        echo "  - External dependencies: Optional"
        echo ""

        # Check if manifest URL is provided
        if [[ "$*" != *"--manifest-url"* ]] && [[ "$*" != *"-u"* ]]; then
            print_warning "No manifest URL provided. Use --manifest-url <url> to enable remote sync."
            echo ""
        fi

        # Start in standard mode
        oneiric start --mode=standard "${@:2}"
        ;;

    help|--help|-h)
        echo "Oneiric Development Startup Script"
        echo ""
        echo "Usage: $0 [lite|standard] [options...]"
        echo ""
        echo "Modes:"
        echo "  lite      Start in lite mode (local only, zero dependencies)"
        echo "  standard  Start in standard mode (remote resolution enabled)"
        echo ""
        echo "Examples:"
        echo "  $0 lite"
        echo "  $0 standard --manifest-url https://example.com/manifest.yaml"
        echo "  $0 standard --watch --refresh-interval 300"
        echo ""
        echo "Options:"
        echo "  All options after the mode are passed directly to 'oneiric start'"
        echo "  See 'oneiric start --help' for available options"
        exit 0
        ;;

    *)
        print_error "Unknown mode: $MODE"
        echo ""
        echo "Usage: $0 [lite|standard|help] [options...]"
        echo ""
        echo "Available modes:"
        echo "  lite      - Local-only mode (< 2 min setup)"
        echo "  standard  - Full-featured mode (~ 5 min setup)"
        echo "  help      - Show this help message"
        exit 1
        ;;
esac

# Check exit status
if [ $? -eq 0 ]; then
    print_success "Oneiric started successfully in $MODE mode"
else
    print_error "Failed to start Oneiric"
    exit 1
fi
