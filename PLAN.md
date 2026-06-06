# Code-Q&A Agent — Project Plan (living document)

**Status:** design v3.1 — locked; Inc 0–6 + Inc 5 RAG/external-knowledge + multi-turn chat + eval
(locate · summarize · trace · clarify/fetch-context router · researcher delegates w/ caps · hybrid doc RAG
[ada-2 ⊕ keyword] + professional corpus + budgeted web search, code-authoritative · content-hash delta · eval).
Remaining: HITL (skipped per request) · Inc 7 expansion · router answer-formatting.
**Branch:** `claude/cool-curie-yyEpt`
**Last updated:** 2026-06-06

> Single source of truth for the design. We update this doc as decisions change so nothing
> is lost in chat. First fixtures: `signify` (Python), `jsign` (Java) — these are *test
> targets*, not the design target. The architecture is general.

---

## 0. Working agreements (process)

- **Plan before code.** No implementation until the plan is approved.
- **Increment cadence.** Each increment: build → explain what/why → on approval → commit + push.
- **Session board.** Start each working session with a short **Done / Doing / Todo** board.
- **Diagram every plan.** Every plan update includes an architecture diagram (ASCII is fine).
- **Structured agent I/O.** All agents emit **structured** outputs. The *only* natural-language
  surface to the user is the conversation router's final answer.
- **Security is a feature** (principle 7), not an afterthought.

---

## 1. Task & goal

Conversational chatbot that answers natural-language questions about a target repo (local clone
or git URL), grounded in actual source, using an LLM (+ embeddings where useful). UI = interactive
CLI. Three question shapes to serve:

- **Locate** — "is there X (e.g. auth) logic, and where?" (retrieval)
- **Summarize** — "what does this application do?" (whole-repo overview)
- **Trace** — "flow (classes & function calls) of executable signing?" (multi-hop call-graph)

---

## 2. Capability scope

**In scope (v1)**
- Multi-turn Q&A over one target repo (local or git URL), **Python + Java**.
- The three modes: locate, summarize, trace.
- Grounded answers with `file:line` citations + corpus-boundary awareness (in-repo vs. third-party).
- Read-only static analysis; SHA-keyed incremental index.
- Full-tree **file inventory** (binary/asset files known by path/type; not downloaded or parsed).
- Multi-agent orchestration with per-role model modularity (Anthropic tiers local-first; Azure alternate).
- Eval harness + full reasoning trace.
- Scope-guard + abuse resistance.

**Out of scope (v1)**
- Writing / refactoring / generating code in the target; fixing its bugs.
- **Executing or building** the target repo (or running its tests) to answer.
- Reading or disassembling **binary file contents** (PE / reverse engineering); binaries are inventory-only.
- Re-implementing what the targets do (we analyze jsign/signify; we don't sign/verify).
- Languages beyond Python/Java; following into third-party dependency source; multi-repo reasoning.
- Proving correctness / exhaustive vulnerability discovery.
- Guaranteed answers on obfuscated / fully dynamic-reflective code (best-effort + honest "can't resolve").
- Production hardening: web UI, multi-user, auth, hosted service, scaled rate-limiting.

**Future development**
- More languages (drop in a Language Profile); **HTML report skill** (router-side presentation).
- **HITL learning loop** (researcher learns from human-review outcomes).
- Heavier knowledge-graph / higher-precision resolution (see §5; future research).
- **Alternative vector store** (e.g. Chroma) — evaluate single-file-index vs. separate-store tradeoff.
- Web/IDE front-ends; server mode; distributed vector store.
- Expanded professional-corpus RAG + web-search grounding.
- External tracing (LangSmith / Datadog).

---

## 3. Design principles

1. **Never depend on whole-repo-in-context.** Always retrieval + structure → scales to any size.
2. **Structure over similarity for depth.** A language-neutral symbol graph is the backbone;
   embeddings only assist "locate."
3. **Agentic multi-hop, not single-shot RAG.** Agents wield a retrieval toolbox and iterate;
   this is the general answer to "follow the references" (Trace) and survives dynamic dispatch / DI / reflection.
4. **Everything behind a seam.** Source, language, retriever, vector store, LLM-per-role, strategy —
   extend by adding an adapter, never a rewrite.
5. **Grounded + boundary-aware.** Answers carry `file:line` citations and know in-repo vs. third-party.
6. **Persisted, incremental index.** Cache keyed by commit SHA; update via `git diff`.
7. **Professional & abuse-resistant.**
   - *Scope discipline:* answers only legitimate, in-scope questions; declines off-topic / resource-wasting
     requests; per-query + per-session budgets (steps/tools/tokens) cap resource-exhaustion abuse.
   - *Code is data, not instructions:* retrieved repo content is untrusted, clearly delimited; the agent
     never executes instructions embedded in the codebase (prompt-injection resistance).
   - *No self-disclosure:* won't reveal system prompts, internal architecture, or credentials
     (anti-reverse-engineering).
   - *Defensive-use framing:* explains security-relevant code; won't produce weaponized output.
   - *Privacy:* target code stays local by default (see tracing, §9).

---

## 4. Architecture

### 4.1 System diagram

```
                          ┌───────────────────────────────┐
                          │        USER  ·  CLI REPL       │
                          │   multi-turn, natural language │
                          └──────┬─────────────────▲───────┘
                        question │   final NL answer │ (+ file:line citations)
                                 ▼                 │
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  CONVERSATION ROUTER  ·  lightweight LLM (Haiku 4.5)                        │
   │  scope-guard → intent → route → COMPILE final answer (NL → user)           │
   │  the ONLY agent that speaks NL to the user; assembles workers' findings    │
   └──┬────▲──────────────────────────────────────────────┬────▲───────────────┘
      │    │                                               │    │
 dispatch │ │ findings                              escalate│ │ report
 (locate) │ │ (structured)                                  │ │ (structured)
      ▼    │                                               ▼    │
   ┌─────────────────────────────┐   team: dispatch ↕   ┌──────────────────────────┐
   │  RETRIEVER WORKERS          │◄────  findings   ────►│  RESEARCHER · heavy LLM   │
   │  mid LLM (Sonnet 4.6) ·×N   │                       │  (Opus 4.8)               │
   │  structured I/O · locate /  │                       │  structured I/O           │
   │  map / connect              │                       │  plans · reasons ·        │
   │  spawned by Router OR       │                       │  synthesizes conclusions  │
   │  Researcher; findings go    │                       │  raises HITL when stuck   │
   │  back to whoever spawned    │                       └──────┬───────────┬───────┘
   │                             │                              │ RAG       │ web (budgeted,
   └─────────────┬───────────────┘                              ▼           ▼  via retriever)
                 │ call tools                            ┌────────────┐ ┌──────────┐
                 ▼                                       │PROFESSIONAL│ │   WEB    │
   ┌────────────────────────────────────────────┐       │CORPUS (RAG,│ │(opt-in,  │
   │  TOOLBOX  (LangChain tools over the index)  │       │user-fed)   │ │ future)  │
   │  search_lexical · search_semantic ·         │       └────────────┘ └──────────┘
   │  get_symbol · find_callers · find_callees · │
   │  get_references · find_implementations ·    │
   │  get_call_path · read_file · repo_overview  │
   └─────────────┬───────────────────────────────┘
                 │ read
                 ▼
   ┌────────────────────────────────────────────────────────────────────────────┐
   │  INDEX · on-disk SQLite · keyed by commit SHA · delta via `git diff`         │
   │   [Symbol Graph]  [Call-Paths]  [Embeddings]  [Repo Map]  [Doc Inventory]    │
   │   nodes+edges:    precomputed   vectors       tree+entry  README/docs        │
   │   calls/imports/  traces from   (local)       points      comments           │
   │   extends/impl    entry points                                               │
   └──────────────────────▲─────────────────────────────────────────────────────┘
                          │ build: tree-sitter + hand-rolled resolution (Option A)
   ┌──────────────────────┴─────────────────────────────────────────────────────┐
   │  INDEXER  ◄─ Language Profiles (tree-sitter): Python · Java · (+pluggable)   │
   │           ◄─ Source Adapter: local path | git clone(url,ref) → pinned SHA    │
   └────────────────────────────────────────────────────────────────────────────┘

   Flow of one answer:  USER → ROUTER → (dispatch) RETRIEVER/RESEARCHER → tools/index
                        → structured findings & report flow BACK UP to ROUTER
                        → ROUTER compiles the single NL answer → USER

   CROSS-CUTTING
   ├─ LLM PROVIDER LAYER · LangChain init_chat_model · per-role model/provider
   │     local-first = Anthropic tiers: router·Haiku 4.5  retriever·Sonnet 4.6  researcher·Opus 4.8
   │     alternate = Azure OpenAI (GPT-4o) · embeddings = separate provider (local / ada-2 / Voyage)
   ├─ TRACING · local structured trace (JSONL): route → tools → reasoning → answer
   │     [future: LangSmith / Datadog]
   ├─ HITL · LangGraph interrupt + checkpointer → human review queue (learning = future)
   └─ EVAL HARNESS (offline) · cases → retrieval-recall + LLM-judge + groundedness
```

### 4.2 Components

- **Source adapter** — `RepoSource`: local path *or* `git clone(url, ref)`; resolves a tree pinned to a
  SHA; language-aware walk with ignore rules (skip vendored/build/binary).
- **Language layer** — `LanguageProfile` registry keyed by extension → tree-sitter grammar + queries for
  `{definitions, imports, calls, inheritance/impl}`. Add a language = add one profile. Ship Python + Java.
- **Indexer → Index (on-disk SQLite, SHA-keyed):**
  - **Symbol Graph** — symbols (file/func/method/class/interface) + edges (contains, imports, calls,
    inherits/implements). Hand-rolled cross-file resolution (Option A, §5).
  - **Call-Paths** — precomputed traces from entry points (the GitNexus "Processes" idea) so Trace
    questions are a lookup + agentic gap-bridging, not N hops from scratch.
  - **Embeddings** — symbol-aware chunks + doc chunks in a `VectorStore` (SQLite via `sqlite-vec`,
    unified with the graph in one file; swappable). **Optional** — see §7.
  - **Repo Map** — tree, detected entry points, dir/module roles.
  - **Doc RAG** — README/markdown/`docs/` split into heading-delimited **doc chunks** (stored in the
    index); queried by `search_docs`. **Hybrid retrieval**: semantic (Azure **ada-2** embeddings in a
    `doc_vectors` table, brute-force cosine) blended with keyword overlap, with **keyword fallback** when
    no embedder is configured. **Code is authoritative** — docs ground *intent*, never override the code (D16).
- **Toolbox** (LangChain tools over the index, one `Retriever` interface):
  `search_lexical` (ripgrep) · `search_semantic` (vectors) · `get_symbol` · `find_callers` ·
  `find_callees` · **`get_references`** (all usage sites of a symbol) · `find_implementations` ·
  `get_call_path` (precomputed traces) · **`find_files`** (inventory incl. binary/asset files) ·
  `read_file(path,range)` · `repo_overview` · **`structure_digest`** (whole-repo module map for summarize).
  A **context assembler** expands from seeds along graph edges to return *connected* sets (not independent
  top-k), with dedup/diversity + token budget.
- **Agent graph (LangGraph) — works like a team:**
  - **Conversation Router** (lightweight LLM) — owns the conversation and is the only NL voice. ONE
    context-aware decision (`router_decision`) chooses to answer directly, **ask a clarifying question**,
    **fetch code context first** (via a retriever, bounded by `max_context_fetches`), or route to a worker;
    it then **presents** every worker result as the single user-facing answer. All router steps share one
    persona + the conversation (D14).
  - **Retriever workers** (mid LLM, ×N parallel) — wield the toolbox; produce **structured findings**;
    **spawnable by the router OR the researcher**, and hand findings back to whoever dispatched them
    (router or researcher).
  - **Researcher** (heavy LLM) — a **pure reasoner that delegates code-reading to retrievers** (no
    `read_file`/`search_lexical`; D15); deep reasoning + **structured conclusions**; orchestrates retrievers
    as a team (back-and-forth, parallel fan-out); optional RAG over a user-fed professional corpus
    (`search_corpus`) and **budgeted web search** (`web_search`, capped per question) for external knowledge;
    **returns a structured report up to the router** for final presentation. *(HITL interrupt = future.)*
  - **Handoffs are typed** (Pydantic schemas) everywhere; only the router's user-facing message is NL.
- **Conversation/state** — multi-turn REPL; session state = history + a **working set** of retrieved
  symbols/files so follow-ups are cheap. LangGraph checkpointer persists state (also enables HITL).
- **LLM provider layer** — LangChain `init_chat_model`; per-role model/provider binding. **Local-first
  default = Anthropic** (router=Haiku 4.5, retriever=Sonnet 4.6, researcher=Opus 4.8, via
  `ANTHROPIC_API_KEY`); **Azure OpenAI = alternate** (wraps the boilerplate's AD token provider).
  Embeddings use a **separate** provider (Anthropic ships none): local code embedder by default, Azure
  ada-2 or Voyage optional; **semantic retrieval is optional** and falls back to lexical+structural if no
  embedder is configured.
- **Caching & delta** — index persisted per (repo, SHA). On rebuild, a **content-hash delta** (`build_delta`)
  reuses parsed symbols/edges/doc-chunks for files whose hash is unchanged and re-parses only changed/new
  ones, then re-runs the cheap global resolution + call-paths. Hash-based, so it covers shallow clones and
  dirty worktrees, not just commit-to-commit diffs (D7). `inspect` prints `delta: reused R, reparsed P`.
- **Tracing & Eval** — see §9.

### 4.3 Graph nodes (LangGraph)

Nodes exist for graph clarity, but every **router-side** node is one brain: the same router model +
`ROUTER_PERSONA` + the conversation history (no isolated per-node personas).

| node | model | role |
|---|---|---|
| `scope_guard` | — (regex) | deterministic abuse / prompt-injection / resource pre-filter |
| `router_decision` | router (Haiku) | the brain: one context-aware call → `answer · clarify · fetch_context · locate · summarize · trace`; can ask the user to clarify, or fetch code first |
| `fetch_context` | retriever (Sonnet) | fetch the code the router asked for, then loop back to `router_decision` (≤ `max_context_fetches`) |
| `retrieve` | retriever (Sonnet) | locate worker: toolbox loop → structured `Findings` |
| `research` | researcher (Opus) + retrievers | trace: plans + delegates code-reading to parallel `retriever#N` → `TraceReport` |
| `present_locate` / `present_trace` / `present_summary` | router (Haiku) | the router presents the worker's results (or the structure digest) as the single user-facing answer |

Flow: `scope_guard → router_decision → { answer|clarify ⇒ end · fetch_context ↺ · retrieve→present_locate · research→present_trace · summarize⇒present_summary }`.

---

## 5. Knowledge-graph decision (GitNexus research outcome)

- **GitNexus is tree-sitter static analysis over an embedded graph DB (LadybugDB/KuzuDB), MCP-native,
  PolyForm-Noncommercial** — i.e. a mature, graph-DB-backed version of what we're building, **not** an
  LLM-extracted KG. **Decision: do not adopt** (license likely blocks commercial use; embedded graph DB +
  large Node/native supply chain we don't need; OSS incremental story weaker than our `git diff` delta).
  It **validates** our tree-sitter + SQLite direction.
- **Ideas we steal (zero new infra):** (1) precomputed **call-paths** from entry points; (2) **git-diff →
  impacted symbols/paths** mapping on the delta cache.
- **Cross-file resolution / edge layer = Option A (hand-rolled tree-sitter resolution).** Locked.
  - *Not now (future research, user-led):* **`stack-graphs`** (best precision, SQLite + incremental, no
    build — but archived Sep 2025, Python cross-module flaky); **SCIP** (highest precision but must *build*
    the repo → violates no-execute principle; opt-in for trusted repos only). **Joern** rejected (JVM,
    heavyweight). Our agentic multi-hop layer is what bridges gaps hand-rolled resolution misses.

---

## 6. Stack

| Concern | Choice |
|---|---|
| Packaging | **UV** |
| Orchestration | **LangGraph + LangChain** (model-agnostic) |
| Config | **Python** (typed settings module); **secrets via `.env`** (`ANTHROPIC_API_KEY`; Azure boilerplate vars) |
| Index store | **SQLite** (symbol graph + call-paths + vectors via `sqlite-vec`; Chroma = future option) |
| Lexical search | **ripgrep** |
| Chat LLM | **Local-first: Anthropic** — router=Haiku 4.5 · retriever=Sonnet 4.6 · researcher=Opus 4.8. **Alternate: Azure OpenAI** (GPT-4o, AD-token auth) |
| Embeddings | **Separate, pluggable provider** (Anthropic has none) — local code embedder (default) · Azure ada-2 · Voyage `voyage-code-3`; **optional** (fallback: lexical+structural) |
| CLI | prompt_toolkit / rich |

---

## 7. Per-role model map

Concrete IDs come from `.env` (e.g. `ROUTER_MODEL` / `RETRIEVER_MODEL` / `RESEARCHER_MODEL` /
`EMBEDDING_MODEL`) — never hardcoded — so provider/model is swappable per role.

**Local-first default = Anthropic** (chosen to actually exercise tier separation across roles):

| Role | Tier (default) | Provider | Why |
|---|---|---|---|
| Router | Haiku 4.5 | anthropic | lightweight orchestration; cheapest (≈1×) |
| Retriever | Sonnet 4.6 | anthropic | mid; tool-calling worker (≈3×) |
| Researcher | Opus 4.8 | anthropic | heavy reasoning (≈5×) |
| Embeddings | local code embedder | local | offline, no key; or Azure ada-2 / Voyage `voyage-code-3` |

Cost ladder is a clean **1 : 3 : 5** (in/out $/1M) — easy to observe tier effects. Note Haiku's context is
**200K** vs **1M** for Sonnet/Opus; fine for the router (it orchestrates, doesn't hold big evidence).

**Alternate = Azure OpenAI** (the boilerplate): one chat deployment (GPT-4o) + ada-2. On the Azure path all
three chat roles collapse to GPT-4o — i.e. **tier separation only exists on the Anthropic path** today;
that's expected and swappable via config when more Azure deployments exist.

---

## 8. Roadmap (increments may merge)

- **Inc 0 — Skeleton.** UV project, Python config + `.env`, LangChain per-role model factory (default
  Anthropic tiers via `ANTHROPIC_API_KEY`; Azure path wraps the boilerplate's AD token provider),
  `RepoSource` (local + clone), minimal LangGraph = router node + scope-guard + smoke round-trip.
- **Inc 1 — Structural index.** tree-sitter profiles (py+java) → SQLite symbol graph + call-paths + repo
  map + doc inventory; SHA cache. `inspect` command dumps stats.
- **Inc 2 — Toolbox + retriever + router fast-path → Locate (Q1).** Seed eval + reasoning trace.
- **Inc 3 — Summarize (Q2).** Doc/structure-first overview.
- **Inc 4 — Researcher + multi-hop Trace (Q3).** Team topology, parallel retrievers, boundary awareness.
- **Inc 5 — RAG grounding + external knowledge.** ✅ Repo-docs RAG (hybrid `search_docs`, ada-2 ⊕ keyword) ·
  ✅ external professional-corpus RAG (`search_corpus`) · ✅ **budgeted web search** (`web_search`, Tavily,
  capped/question) — all code-authoritative (D16/D17). *(HITL skipped per request → future.)*
- **Inc 6 — Incremental delta indexing.** ✅ Content-hash delta → reuse unchanged files, re-parse only
  changes, re-assemble globally (`build_delta`); auto-used by `ensure_index` when a prior index exists.
- **Inc 7 — Eval expansion + trace report.** *(Future: HTML report skill, HITL learning loop.)*

---

## 9. Eval & tracing

- **Reasoning trace (explainability):** every query emits a structured trace — router decision + rationale →
  route taken → each retriever's tool calls + results → researcher reasoning + evidence → findings/report
  returned to router → final answer + citations. **Default = local-first JSONL** (keeps sensitive code
  on-machine). **LangSmith / Datadog = future dev** (they ship traces externally).
- **Eval harness (offline, repo-agnostic):** Python-defined cases `{question, expected paths/symbols,
  rubric, type}` → retrieval recall/hit-rate + LLM-judge against rubric + groundedness (cited files real &
  relevant). Includes boundary/negative cases (e.g. "can signify sign?" → no; "where is the real crypto?"
  → third-party). Seeded at Inc 2, expanded at Inc 7. Metrics finalized with user.

---

## 10. Decisions log

- **D1** Read-only static analysis; never execute/build the target repo (security).
- **D2** tree-sitter + SQLite symbol graph; **hand-rolled resolution (Option A)**; skip GitNexus.
- **D3** Multi-agent (LangGraph): lightweight **router** / mid **retriever(s)** / heavy **researcher**;
  team topology (router *and* researcher can spawn retrievers; retrievers report back to dispatcher).
  All findings/reports flow **back up to the router**, which compiles the single user-facing answer.
- **D4** Per-role model modularity via LangChain. **Local-first default = Anthropic tiers**
  (router=Haiku 4.5 · retriever=Sonnet 4.6 · researcher=Opus 4.8) to exercise true tier separation;
  **Azure OpenAI = alternate** (GPT-4o + ada-2).
- **D5** **UV** packaging; **Python config**; secrets via `.env`.
- **D6** **Local-first structured tracing**; LangSmith/Datadog = future.
- **D7** Precompute **call-paths**; **incremental delta = per-file content-hash** → reuse parsed results
  for unchanged files, re-parse only changes, re-resolve globally (works for shallow clones / dirty trees,
  not just commit diffs). Implemented Inc 6 (`build_delta`).
- **D8** **Structured agent outputs** everywhere except the router's user-facing answer.
- **D9** Toolbox includes **`get_references`** (usage sites of a symbol).
- **D10** Embeddings via a **separate, pluggable provider** (Anthropic ships none). **Wired: Azure ada-2**
  (`AzureOpenAIEmbeddings`, same Entra-ID auth as chat) powering **hybrid `search_docs`** (semantic ⊕
  keyword) over a `doc_vectors` table; local sentence-transformers is an optional extra. **Semantic is
  additive** — embedded incrementally (only un-embedded chunks), cached in the index, and it **falls back
  to keyword** when no embedder is configured or a call fails. Brute-force cosine (corpus is small → no
  `sqlite-vec` needed; D11 store stays single-file SQLite).
- **D11** Vector store stays **SQLite** (unified single-file index via `sqlite-vec`); Chroma evaluated and
  **deferred to future dev** (single-file-index vs. separate-store tradeoff).
- **D12** Git ingestion uses a **lean clone** (shallow + blobless `--filter=blob:none` + sparse-checkout to
  source/docs), but the index inventories the **full tree** (binary/asset files recorded as metadata via
  `git ls-tree`). Reading binary *contents* is out of scope. Plain-clone fallback for older git.
- **D13** Every reasoning-trace event is attributed to an **agent/instance** (e.g. `router`, `retriever#1`)
  to keep multi-agent flows legible — important once the researcher fans out to parallel retrievers.
- **D14** **Router is one brain.** A single context-aware `router_decision` makes all lightweight decisions
  (scope reasoning, **clarify**, intent, **fetch_context**) with the conversation in view; all router-side
  steps (decision + every presentation) share one persona + history. Nodes stay split for clarity only.
  `fetch_context` is a **narrow peek to answer a small question** — never a way to gather breadth or
  "prepare" before routing; comparison / flow / multi-thread questions route straight to `trace` so the
  **researcher** fans out. Budget-exhausted `fetch_context` coerces to `trace` on the whole question.
- **D15** **Researcher is a pure reasoner** — it plans over the structural tools and **delegates all
  code-reading/searching to retriever workers** (`spawn_retrievers`); it has no `read_file`/`search_lexical`.
  Clean tier separation: Opus reasons, Sonnet fetches.
- **D16** **Docs ground intent; code is authoritative.** Repo documentation (README/markdown/`docs/`) is
  chunked by heading into the index and retrieved via `search_docs` to explain *why*/design. Docs can
  drift or be aspirational, so behavioral claims are **verified against code, and code wins on conflict**.
  Both researcher and retriever may consult docs (it is not a `_DELEGATED` code-reading tool).
- **D17** **External knowledge is budgeted and subordinate to code.** The professional corpus
  (`search_corpus`, separate store) and **web search** (`web_search`, capped at `web_search_max`/question,
  Tavily via stdlib `urllib`, off by default) supply standards/background but are **provenance-tagged as
  external and never override the repo's actual code** (extends D16). HITL learning loop deferred.

## 11. Assumptions log

- **A1** Local-first creds = `ANTHROPIC_API_KEY` (chat tiers Haiku/Sonnet/Opus); Azure creds
  (GPT-4o + ada-2) available as the alternate. Anthropic provides **no** embeddings model.
- **A2** Outbound network available for `git clone` + the chosen LLM provider (clone verified working).
- **A3** Single target repo per session; Python/Java only for v1.
- **A4** Professional-corpus RAG is user-supplied and optional (empty by default). Implemented Inc 5:
  `--corpus <dir>` (or `CORPUS_PATH`) → a **separate** hybrid store (chunks + ada-2 vectors, keyed by dir +
  content hash) exposed as `search_corpus` — external reference knowledge, never an override of repo code.
- **A5** Repo pinned at a commit SHA for reproducibility/delta.
