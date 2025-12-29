# ONNXRuntime Usage Guide for Python 3.13 (3.14 Planned)

Oneiric currently targets Python 3.13. When testing Python 3.14 (planned), ONNXRuntime wheels may lag behind new releases. This guide explains how to work with ONNXRuntime when needed.

## The Issue

- Python 3.14 upgrades can outpace ONNXRuntime wheel availability.
- When dependencies try to import ONNXRuntime under Python 3.14, import errors may occur.
- This is expected to resolve once ONNXRuntime publishes Python 3.14-compatible wheels.

## Solution: Using uvx

Use `uvx` to run ONNXRuntime-dependent code with Python 3.13 if you are testing Python 3.14:

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


For more complex ONNXRuntime workflows, keep a dedicated Python 3.13 virtualenv that includes `onnxruntime`, `numpy`, and `pandas`.

## When This Will Be Resolved

This workaround will no longer be necessary when ONNXRuntime releases wheels compatible with Python 3.14.
