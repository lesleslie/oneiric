# ONNXRuntime Usage Guide for Python 3.14

This project uses Python 3.14, but ONNXRuntime does not yet have compatible wheels for this Python version.
This guide explains how to work with ONNXRuntime when needed.

## The Issue

- Python 3.14 is very new and ONNXRuntime wheels have not been compiled for this version yet
- When crackerjack (or other dependencies) try to use ONNXRuntime, import errors may occur
- This is a temporary issue that will resolve when ONNXRuntime releases Python 3.14-compatible wheels

## Solution: Using uvx

Use `uvx` to run ONNXRuntime-dependent code with Python 3.13 while keeping your main project on Python 3.14:

```bash
# Run Python scripts that use ONNXRuntime
uvx --python 3.13 --with onnxruntime python your_script.py

# Install and run ONNXRuntime tools
uvx --python 3.13 --with onnxruntime onnxruntime_tools

# Run specific ONNXRuntime commands
uvx --python 3.13 --with onnxruntime python -c "import onnxruntime; print(onnxruntime.__version__)"
```

## Example: ONNX Model Conversion Script

If you need to convert ONNX models, create a script that uses uvx:

```bash
#!/bin/bash
# onnx_convert.sh
uvx --python 3.13 --with onnxruntime,pyyaml,numpy python convert_model.py "$@"
```

## Alternative: Development Docker Container

For more complex ONNXRuntime workflows, consider using a development container with Python 3.13:

```dockerfile
FROM python:3.13-slim

RUN pip install onnxruntime numpy pandas

# Your ONNXRuntime workflow commands here
```

## When This Will Be Resolved

This workaround will no longer be necessary when ONNXRuntime releases wheels compatible with Python 3.14.
Monitor the ONNXRuntime PyPI page for updates: https://pypi.org/project/onnxruntime/