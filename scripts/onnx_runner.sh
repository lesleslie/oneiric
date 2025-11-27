#!/bin/bash
# onnx_runner.sh - Execute ONNXRuntime-dependent Python code using Python 3.13 via uvx

set -e

# Check if a Python file was provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <python_script.py> [args...]"
    echo ""
    echo "This script runs ONNXRuntime-dependent Python code with Python 3.13"
    echo "while keeping your main project on Python 3.14."
    exit 1
fi

SCRIPT="$1"
shift

# Run the script with ONNXRuntime in Python 3.13 environment
uvx --python 3.13 --with onnxruntime,pyyaml,numpy,pandas python "$SCRIPT" "$@"