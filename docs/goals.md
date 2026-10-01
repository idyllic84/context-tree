# Goals and scope

## Problem

An agent's conversation history mixes goals, implementation attempts, corrections, tool activity, explanations and unrelated work. Chronological proximity is not the same as task relevance. A long prompt can include all the information yet still make the agent spend effort rediscovering which parts matter.

Context Tree asks whether task structure can turn that history into an external, addressable context store: preserve historical material, identify the relevant branch for the current interaction, recover necessary dependencies, and omit unrelated branches from active context.

## Primary objective

At a fixed quality requirement, reduce the history the consuming agent must read and reconstruct. Ideally, active context grows with the needs of the current task rather than with all work ever discussed. This is a research objective, not a property already demonstrated at arbitrary scale.

There are three distinct layers:

1. **Organization:** represent work relationships, hierarchy, feedback and scope while retaining source links.
2. **Selection:** locate relevant nodes, form coherent branches, expand missing evidence and reject distractions.
3. **Runtime use:** give a consuming agent a small sufficient working context and recover detail when necessary.

The current prototype implements organization and query-driven selection/assembly. It does not automatically intercept another agent's calls or evict that agent's complete conversation history.

## Why a task tree?

A goal explains why several tasks belong together. Parent constraints can apply to descendants. Alternatives can belong to the same problem without being simultaneously valid. A task branch can therefore supply a coherent context unit rather than disconnected semantically similar snippets.

A tree cannot express every relationship. Cross-branch references, changed requirements and incorrect parentage can defeat simple pruning. File links, explicit identifiers and query-time expansion supplement hierarchy. The implementation must be compared against strong flat and non-task-hierarchical baselines; the tree is a hypothesis, not an axiom.

## Non-goals for this version

- A universal personal fact memory or autonomous knowledge graph of the whole repository.
- AST analysis or ingestion of arbitrary source files merely because an agent touched them.
- A replacement for Git, project instructions, issue tracking or an agent execution framework.
- Automatic multi-device synchronization, multi-provider session adaptation or team access control.
- Guaranteed lossless summarization, optimal retrieval or logarithmic search.

## Success criteria

Evaluate organization and selection independently:

- explicit fact and feedback-target coverage;
- correct goal/task hierarchy, unit ownership and constraint scope;
- relevant-branch recall and irrelevant-branch rejection;
- necessary ancestor/dependency coverage;
- faithful context assembly with valid provenance;
- active context size at comparable quality;
- localization latency, extra browsing calls and all-model token usage;
- ingestion/maintenance cost amortized over realistic reuse.

Use negative cases: no relevant history, highly similar but unrelated tasks, stale decisions, ambiguous references and evidence outside the current branch. Smaller output is not success if it drops what the task needs.
