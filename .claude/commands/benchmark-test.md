Run the benchmark orchestrator in **test mode** (quick validation):

**Duration**: ~5-10 minutes
**Cost**: ~$0.50-1.00
**Scope**: 2 cold + 5 warm starts, 1 memory size (1769 MB)

```bash
uv run python scripts/benchmark_orchestrator.py
```

After completion:
1. Extract and display the **test-run-id** from the output
2. Show summary of results written (should be ~210 results + 60 aggregates)
3. Offer to run analysis: `/analyze` with the test-run-id
