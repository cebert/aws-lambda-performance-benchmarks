# Contributing to AWS Lambda ARM vs x86 Benchmark

Thank you for your interest in contributing to this benchmark project! This is a research-focused project comparing AWS Lambda performance across architectures and runtimes.

## Before You Start

1. **Read the documentation:**
   - [DECISIONS.md](../DECISIONS.md) - Understand architectural decisions and design rationale
   - [docs/benchmark-design.md](../docs/benchmark-design.md) - Review benchmark methodology
   - [README.md](../README.md) - Understand project scope and goals

2. **Check existing issues** to see if your idea or bug has already been reported

## How to Contribute

### Reporting Issues

When reporting issues, please include:

- **For bugs:**
  - Steps to reproduce
  - Expected vs actual behavior
  - Environment details (AWS region, runtime versions, etc.)
  - Relevant logs or error messages

- **For feature requests:**
  - Clear description of the proposed feature
  - Rationale for why it's valuable to the benchmark
  - Consideration of how it aligns with existing ADRs

### Pull Requests

1. **Fork the repository** and create a feature branch from `main`
2. **Make your changes:**
   - Follow existing code style and conventions
   - Update documentation if you're changing functionality
   - Add/update tests if applicable
3. **Test your changes:**
   - Run linters: `npm run lint`
   - Build the project: `npm run build`
   - Test deployment if infrastructure changes: `npm run deploy`
4. **Commit with clear messages:**
   - Use conventional commits format: `feat:`, `fix:`, `docs:`, `chore:`, etc.
   - Reference issues when applicable
5. **Submit a pull request** with:
   - Clear description of changes
   - Rationale for the change
   - Any breaking changes or ADR updates needed

## Code Style

- **TypeScript/JavaScript:** ESLint + Prettier (automatically enforced)
- **Python:** Ruff (PEP 8 compliant)
- **Documentation:** Markdown with clear headings and examples

## Adding New Runtimes or Workloads

If you're adding a new runtime or workload:

1. Update `cdk/lib/config/lambda-config.ts`
2. Create handler in `lambdas/<runtime>/<workload>/`
3. Follow the [handler API spec](../docs/handler-api-spec.md)
4. Update `scripts/benchmark_utils.py` if needed
5. Add documentation and update README
6. Consider adding an ADR to DECISIONS.md

## Testing

- **Quick validation:** `npm run benchmark:test`
- **Full testing:** Deploy and run balanced mode benchmark
- **Infrastructure:** Test in a non-production AWS account

## Documentation Standards

- Keep documentation concise and focused
- Use code examples where helpful
- Update relevant docs when changing functionality
- Follow existing documentation structure

## Questions?

Open an issue with the `question` label or start a discussion.

## License

By contributing, you agree that your contributions will be licensed under the same license as this project (see [LICENSE](../LICENSE)).
