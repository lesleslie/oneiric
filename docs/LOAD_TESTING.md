# Load Testing

Use the built-in load test harness to stress concurrency and measure latency/throughput
without wiring external services.

## CLI Usage

Run a basic load test:

```bash
uv run python -m oneiric.cli load-test --total 1000 --concurrency 50 --sleep-ms 5
```

Simulate CPU work with a payload hash:

```bash
uv run python -m oneiric.cli load-test --total 2000 --concurrency 100 --payload-bytes 512
```

Emit results as JSON (machine-readable):

```bash
uv run python -m oneiric.cli load-test --total 1000 --concurrency 50 --json
```

## Notes

- Use `--warmup` to prime the event loop or caches before measuring.
- Use `--timeout` to cap total run time; cancellations count as errors.
