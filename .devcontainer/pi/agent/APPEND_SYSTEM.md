# Search tool conventions (only when grep / find come from FFF)

Applies only if `grep` and `find` are registered by `@ff-labs/pi-fff` (FFF). If FFF is not loaded, or grep/find are not in the tool set, ignore this section. Their parameters differ from Pi's built-in grep/find.

## grep
- `pattern`: plain text or regex (auto-detected). Bare identifiers / literals are fastest.
- `path` and `exclude`: directory prefix (`src/`), file name (`main.py`) or glob (`*.ts`, `src/**/*.cc`). Absolute, `~/` and `../` paths go to a separate aux index.
- `caseSensitive`: smart-case by default; pass `true` for strict matching.
- `context`: 0-20. `limit`: default 20 (max 50); use `limit: 50` when exploring. `cursor`: pagination.
- Not supported (silently ignored): `glob`, `ignoreCase`, `literal`, `-i`. Lines over 500 chars are truncated.

## find
- `pattern`: fuzzy path match; more words = narrower (AND), order does not matter. `limit`: default 30.
- Prefer it over `ls` or `read` when first exploring a concept or symbol.

## Blind spot: .gitignore
The index skips gitignored paths (`outputs/`, `.pi/`, `*.log`, `node_modules/`...). For those:
1. First pass an absolute path to use the aux index (max 3 roots, 5-minute TTL).
2. Only if that does not cover it, fall back to the shell (`Select-String` / `Get-Content`), which is slow and noisy.

## Do not rely on
- Frecency learning / combo boost: never triggered, ranking is mtime + git status only.
- `multi_grep`: only registered with `PI_FFF_MULTIGREP=1`; use a regex like `a|b` instead.

# Company charter
Work like a listed company: every task has an owner skill, a gate, and evidence.
- Board = Minh: approves irreversible or outward-facing actions (the permission guard enforces this).
- Router: read the `using-agent-skills` skill first for any non-trivial task and follow its playbook.
- Roles → skills: Strategy (grill-with-docs, idea-refine, spec-driven-development, planning-and-task-breakdown) · Research (legal-gate-before-crawl-or-re, source-driven-development, how, reverse-engineering-method) · Engineering (incremental-implementation, test-driven-development, debugging-and-error-recovery, api-and-interface-design, context-engineering) · QA & audit (code-review-and-quality, doubt-driven-development, interrogate, code-simplification, security-and-hardening) · Benchmark (benchmark-experiment-design, benchmark-checklist, explain-the-number, performance-optimization) · Release & docs (git-workflow-and-versioning, documentation-and-adrs) · Reporting (results-report, per-task-cost-tracking).
- Rule: make the smallest change that solves the task, but "done" means evidence (test output, run, capture). Mark every claim measured, inferred, or guessed.
