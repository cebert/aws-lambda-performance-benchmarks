Analyze benchmark results from a test run.

1. **Ask the user for the test-run-id** (from benchmark output)

2. **Optional filters** - ask if they want to filter by:
   - `--runtime` (python3.13, python3.12, python3.11, nodejs22, nodejs20)
   - `--workload` (cpu-intensive, memory-intensive, light)
   - `--architecture` (arm64, x86_64)

3. **Run analysis**:
   ```bash
   uv run python scripts/analyze_results.py <test-run-id> [filters]
   ```

4. **Display key findings** from the output:
   - Performance comparisons (ARM vs x86)
   - Cost analysis
   - Optimal memory configurations
   - Any anomalies or unexpected patterns
