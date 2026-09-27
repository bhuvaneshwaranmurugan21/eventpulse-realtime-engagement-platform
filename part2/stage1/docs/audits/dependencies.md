# Part 2 Stage 1 dependency qualification

Qualification used CPython 3.12.14 on Linux in disposable environments. Runtime dependencies are `jsonschema==4.26.0` and `boto3==1.43.102`; the full transitive runtime set is hash-locked. Development gates use exact pins for Ruff, mypy, Coverage, Bandit, pip-audit and build tooling, with a complete CPython 3.12 Linux wheel lock.

The initial `pip==26.0.1` candidate was rejected after the vulnerability scanner reported applicable 2026 advisories. It was replaced by `pip==26.2.1`; the repeated audit reported no known vulnerabilities. Direct dependency licenses are MIT or Apache-2.0 where declared; `pip-audit` does not publish a normalized license expression, so its distribution metadata and upstream package license remain part of the retained qualification record.

Both runtime and development locks contain one SHA-256-qualified wheel per distribution for the qualified CPython 3.12 Linux target. A second environment must install from those wheels with `--no-index --require-hashes`; equivalence is a publication gate. The Lambda artifact vendors the complete runtime set rather than relying on an unspecified runtime SDK version.

The validator invokes only four fixed Git read commands through the absolute executable returned by `shutil.which`: changed-file inventory, status inventory, predecessor tree lookup and ancestor verification. Narrow `S603` annotations document this reviewed no-shell boundary; arguments contain only source constants and `HEAD`, never user input. No scanner category is globally disabled.
