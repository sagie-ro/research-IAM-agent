# code-qa

A conversational agent that answers natural-language questions about a **code repository** —
grounded in the actual source, with `file:line` citations.

Multi-agent (LangGraph): a lightweight **router** owns the conversation and is the single voice;
mid-tier **retriever** workers wield a toolbox over a structural index of the repo; a heavy
**researcher** handles deep multi-hop questions by planning and delegating reading to parallel
retrievers. Documentation, an optional external corpus, and the web ground *intent* — but the
**code is always authoritative**. Design source of truth: **[`PLAN.md`](./PLAN.md)** (architecture
diagram + decision log).

> Reference targets: [`signify`](https://github.com/ralphje/signify) (Python) and
> [`jsign`](https://github.com/ebourg/jsign) (Java) — fixtures; the design is general.

## What it answers

1. **Locate** — "Is there auth/verification logic? Where?" → a retriever.
2. **Summarize** — "What does this application do?" → the router presents a whole-repo digest.
3. **Trace** — "What's the flow (classes & calls) of executable signing?" → the researcher fans out
   to parallel retrievers, **boundary-aware** (it flags where a flow leaves the repo into third-party
   libraries).

The router also **answers** trivial/contextual questions directly, asks a **clarifying** question
when a request is ambiguous, or **fetches a bit of code** before deciding.

## How it works

```
clone (lean) → tree-sitter → SQLite: symbol graph + precomputed call-paths + repo map + doc chunks
              keyed by commit SHA · incremental: content-hash delta re-parses only changed files
question → router brain: scope-guard → ONE decision
           { answer · clarify · fetch_context · locate · summarize · trace }
        → workers: retriever#N (toolbox) / researcher (plans + parallel retrievers)
        → router presents one cited answer   (typed handoffs throughout)
```

- **Read-only & offline-first:** never builds or executes the target. Git URLs use a *lean clone*
  (blobless + sparse-checkout) downloading only source/docs; the full tree (incl. binaries) is still
  inventoried as metadata.
- **Incremental index:** re-opening a repo re-parses only files whose content changed (`build_delta`),
  then re-resolves the graph globally — works for shallow clones and dirty worktrees.
- **Toolbox:** `repo_overview`, `structure_digest`, `get_symbol`, `find_callers`/`find_callees`,
  `get_references`, `find_implementations`, `get_call_path`, `find_files`, `read_file`,
  `search_lexical`, **`search_docs`** (hybrid doc RAG), and **`search_corpus`** (when an external
  corpus is configured). The researcher additionally has a budgeted **`web_search`**.
- **Grounding, code-authoritative:** repo docs / external corpus / web supply design intent and
  background, but behavioral claims are verified against code, and **code wins on conflict**.

## Install

Requires Python 3.11+, [`uv`](https://docs.astral.sh/uv/), and `git`. `ripgrep` (`rg`) is recommended
for lexical search (a pure-Python fallback is used if it's absent).

```bash
uv sync
cp .env.example .env          # then fill in your provider creds
# optional: local embeddings instead of Azure ada-2
# uv sync --extra semantic
```

## Configuration (`.env`)

Two interchangeable chat providers; the LLM layer maps roles → deployments, so switching needs no
per-role edits:

- **Anthropic** (default) — set `ANTHROPIC_API_KEY`; roles bind to tiers (router→Haiku, retriever→Sonnet,
  researcher→Opus) via `ROUTER_MODEL` / `RETRIEVER_MODEL` / `RESEARCHER_MODEL`.
- **Azure OpenAI** — set `LLM_PROVIDER=azure_openai` + `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_VERSION`
  + an Entra-ID service principal; **one** chat deployment `AZURE_OPENAI_MODEL_GPT4O` serves every role.

**Embeddings** (which power semantic doc RAG) are a separate provider: set `AZURE_OPENAI_MODEL_ADA2`
and ada-2 is used automatically — independent of the chat provider; otherwise doc search falls back to
keyword. **Web search** for the researcher defaults to keyless DuckDuckGo (`WEB_SEARCH_PROVIDER`; Tavily
optional). See [`.env.example`](./.env.example) for the full, commented template.

## Usage

```bash
# Ask about a repo. --show-trace prints the agent-by-agent reasoning.
uv run code-qa chat --repo https://github.com/ebourg/jsign \
  --once "What is the flow of executable signing?" --show-trace

# Interactive REPL (follow-ups keep context; /reset clears, /exit quits):
uv run code-qa chat --repo /path/to/repo

# Ground reasoning in external reference docs (standards, design notes):
uv run code-qa chat --repo /path/to/repo --corpus ~/refs/signing-standards

# Build / inspect the structural index (inspect shows delta reuse + doc-chunk counts):
uv run code-qa index   --repo /path/to/repo
uv run code-qa inspect --repo /path/to/repo

# Offline eval suite (retrieval recall · groundedness · LLM-judge; needs an LLM key):
uv run code-qa eval
```

`chat` with no `--repo` runs in chat-only mode (no code retrieval).

## Development

```bash
uv run --with pytest pytest
```

The **key-free** suite covers the deterministic seams — parsing, indexer + delta, toolbox, hybrid
doc/corpus search, scope-guard, graph, web-search budgeting, provider resolution — using fake
embedders / stub models where an LLM or network would otherwise be needed. LLM-driven paths are
exercised via `chat` or `eval` with a key. (`--with pytest` runs pytest inside uv's project env, so a
`pyenv` shim on `PATH` can't shadow it.)

## Status

Increments 0–6 implemented: provider seam · tree-sitter→SQLite index with precomputed call-paths ·
retrieval toolbox + retriever (**Locate**) · structure-first **Summarize** · researcher + multi-hop
**Trace** · conversational **router-brain** (clarify / fetch-context) · hybrid documentation RAG
(ada-2 ⊕ keyword) + external corpus + budgeted web search, all code-authoritative · incremental
content-hash **delta indexing** · offline eval metrics. The HITL learning loop is deferred. See
`PLAN.md` §8 for the roadmap and §10 for the decision log.
