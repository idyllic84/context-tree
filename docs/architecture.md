# Current architecture

This describes the executable package, not the earlier drafts in [history](history/README.md).

## Code boundaries

```text
common/       data classes, paths, SQLite, model transport, JSON CLI and evaluation harness
stages/       one directory per algorithm step, each with processor.py/run.py/evaluate.py
pipeline/     full sync and query orchestration
tools/        package checks, evaluation CLI and read-only Obsidian export
legacy/       retained single-pass extraction experiment, not the default path
```

The original flat `retrieval.py` has been split: `index` owns lookup construction, `recall` owns candidate/evidence queries, `branches` owns topology and expansion, `select` owns one action decision, and `context` owns final assembly. The multi-step query loop lives in `pipeline/retrieval.py`. Shared prompt/wire-format rendering is in `common/context_view.py`; provider transport is only in `common/llm.py`.

## Extraction and organization

### Ingest

The adapter groups one real user message with the assistant text and file operations it triggers. The preceding response is retained separately as reaction context. Multiple assistant text blocks accumulate. A following user message or explicit completion signal closes a turn; unfinished material is retained as pending.

Tool results, sidechains, compact summaries and known CLI wrappers are filtered. File paths come from tool metadata and explicit textual references; source file contents are not opened to build the memory. Parsing remains dependent on the source log format.

### Extract

L1 produces human speech acts (`instruct`, `constrain`, `ask`, `affirm`, `reject`, `answer`, `report`) and at most one dominant agent act per action span. Feedback points to an earlier agent unit. IDs are normalized with reference remapping; split recovery processes earlier batches before later dependent batches.

The adapter's head/tail representation is lossy. Keeping full `agent_raw` in storage does not mean every extraction call sees it. Evidence omitted by truncation may never enter the extracted structure.

### Tree, review and reflexion

L2 consumes fixed units plus current tree state and emits typed mutations. The state machine manages goals, nested tasks, active state, feedback acceptance, constraints and source associations. It validates references and rejects cycles. A recovered tree resumes IDs above existing maxima.

`review` conservatively repairs tree boundaries using iterative mutations. `reflexion` compares claims with a bounded dialogue view to propose evidence-supported removals, additions or moves. These are different objectives and have separate model configuration. Neither is an independent proof of truth; malformed output and evidence truncation remain limitations.

### Framing and emission

Framing gives source-linked agent units compact purpose titles and bodies. Acceptance is not inferred from fluent wording: hard, soft, rejected and unclaimed states must remain distinct.

Emission generates task-derived entities and file/directory edges. Several files in one directory can be folded into a directory relation. Agent content uses session/unit identity rather than a generated title as its stable identity. Metadata retains task and turn references.

### Resolution, indexing and persistence

Path entities bypass semantic embedding and fuzzy resolution. Most task-specific semantic records should not be merged across unrelated work. The resolver remains a separate inherited step; its current bypass path has offline checks, not a comprehensive entity-resolution benchmark.

SQLite contains nodes, edges, processing state, goal/task embedding indexes and literal identifier occurrences. JSON snapshots preserve session/task structures. Version-2 turn caches reject older semantics rather than silently combining them.

Identifier indexing extracts literal code-like names from visible dialogue. It does not infer AST symbols. Ambiguous occurrences without reliable unit/task association remain unassigned. They must not create fabricated task provenance.

## Query processing

1. Embed the query and scan goal/task vectors for candidates.
2. Add exact identifier/file matches when available.
3. Load candidate session snapshots and group nodes by task topology, not cross-session embedding clusters.
4. Include local parent/sibling/child context and inherited constraints; prefetch bounded evidence.
5. The `select` model emits expand/drop/search/done. Newly fetched results must be observed before a model can rely on them.
6. The independently configured `context` model receives selected observed evidence, not the selector's prose as ground truth, and produces compact candidates.
7. References are validated against visible nodes; unrelated work remains separate.

An empty selection avoids the assembly call. A nonempty query typically includes an extra assembly request. Do not reuse older single-loop latency measurements as the cost of this split design.

## Incremental behavior and boundaries

Completed turns are tracked by source identity and cached snapshots. New complete turns extend the existing tree; pending responses are not prematurely treated as final. Unchanged input does not clear the tree. Entity replacement, indexes and processing markers participate in the session update transaction; cache files are written atomically afterward.

This is not arbitrary history editing support. A changed or removed finalized turn can require an explicit rebuild in a separate database. Discovery still has format-dependent change detection. Historical resume/fork metadata does not establish fully tested forest merging.

## Known limitations

- Dense lookup scans the indexes. A task tree does not imply `O(log n)` retrieval.
- LLM extraction, summaries and branch decisions can omit or misassign evidence.
- Same-scope constraint conflicts and staleness are not fully formalized.
- The compact view can omit fields; full source availability is not guaranteed by a short output.
- No runtime hook replaces an external agent's full context window.
- The new standalone package and stage boundaries require new online integration measurements.

See [roadmap](roadmap.md) for the distinction between implemented behavior and unvalidated goals.
