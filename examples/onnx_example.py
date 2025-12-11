#!/usr/bin/env python3
"""
Example ONNXRuntime script to demonstrate the uvx solution for Python 3.14 compatibility.
This script would normally fail with Python 3.14 due to ONNXRuntime compatibility issues.
"""

import sys

import onnxruntime as ort

print(f"Python version: {sys.version}")
print(f"ONNXRuntime version: {ort.__version__}")

# Example: List available execution providers
print(f"Available execution providers: {ort.get_available_providers()}")

# This would be where you load and run your ONNX model
# session = ort.InferenceSession("your_model.onnx")
# result = session.run(None, {"input": input_data})

print("ONNXRuntime is working correctly!")
