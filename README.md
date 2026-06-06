# code-qa

A conversational agent that answers natural-language questions about a **code
repository** — grounded in the actual source, with `file:line` citations.

It is a multi-agent system (LangGraph): a lightweight **router** orchestrates the
conversation and compiles answers, mid-tier **retriever** workers wield a toolbox over
a structural index of the repo, and (coming) a heavy **researcher** handles deep
multi-hop questions. Design source of truth: **[`PLAN.md`](./PLAN.md)** (incl. the
architecture diagram and decision log).

> First test targets: [`signify`](https://github.com/ralphje/signify) (Python) and
> [`jsign`](https://github.com/ebourg/jsign) (Java). They are fixtures — the design is general.

## Question shapes it targets

1. **Locate** — "Is there auth/verification logic? Where?" *(working)*
2. **Summarize** — "What does this application do?" *(next)*
3. **Trace** — "What is the flow (classes & calls) of executable signing?" *(planned)*

## How it works (short version)

```
clone (lean) → tree-sitter index (symbol graph + call-paths) in SQLite, keyed by commit SHA
question → router: scope-guard → classify → retriever#N (toolbox) → router compiles cited answer
```

- **Read-only & offline-first:** we never build or execute the target. Git URLs use a
  *lean clone* (blobless + sparse-checkout) that downloads only source/docs; the full
  file tree (incl. binaries) is still inventoried as metadata.
- **Toolbox:** `repo_overview`, `get_symbol`, `find_callers`/`find_callees`,
  `get_references`, `find_implementations`, `get_call_path`, `find_files`, `read_file`,
  `search_lexical` (ripgrep).
- **Per-role models:** swappable per agent role via `.env` (see below).

## Install

Requires Python 3.11+, [`uv`](https://docs.astral.sh/uv/), `git`, and `ripgrep` (`rg`).

```bash
uv sync
cp .env.example .env     # then set your key(s)
```

Local-first default provider is **Anthropic** (set `ANTHROPIC_API_KEY`), with the agent
roles bound to tiers: router → Haiku, retriever → Sonnet, researcher → Opus. **Azure
OpenAI** is the alternate (set `LLM_PROVIDER=azure_openai` + the Azure vars). Embeddings
are a separate, optional provider (not required for the current increments).

## Usage

```bash
# Ask about a repo (Locate works today). --show-trace prints the agent-by-agent flow.
uv run code-qa chat --repo https://github.com/ralphje/signify \
  --once "Is there signature-verification logic? Where?" --show-trace

# Interactive REPL on a local clone:
uv run code-qa chat --repo /path/to/repo

# Build / inspect the structural index:
uv run code-qa index   --repo /path/to/repo
uv run code-qa inspect --repo /path/to/repo

# Run the eval seed (retrieval recall; needs an LLM key):
uv run code-qa eval
```

A `chat` question with no `--repo` runs in chat-only mode (no code retrieval).

## Development

```bash
uv sync                  # installs the dev group (pytest)
uv run pytest            # key-free tests: parsing, indexer, toolbox, scope-guard, graph
```

The test suite covers the deterministic seams; the LLM-driven router/retriever paths are
exercised manually (`chat`) or via `eval` with a key.

## Status

Increments 0–2 complete: project skeleton + provider seam, the tree-sitter → SQLite
structural index, and the retrieval toolbox + retriever worker answering **Locate**
questions with citations. See `PLAN.md` §8 for the roadmap.
