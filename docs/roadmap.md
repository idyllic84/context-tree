# Roadmap and limitations

## Implemented

- User-triggered dialogue spans with preceding-response context and pending turns.
- Independent L1 extraction, L2 task-tree construction, structural review, evidence reflexion and framing.
- Persistent session snapshots, schema checks, stable unit references and isolated data paths.
- Literal identifier occurrence indexing and file-linked recall alongside dense candidate lookup.
- Task-topology branch grouping, inherited constraints and iterative evidence expansion.
- Separately configurable selection and context assembly.
- Stage-specific model/effort configuration and bounded serial requests.
- Independent stage directories, JSON run entries, local evaluation cases and network-disabled smoke checks.
- Full historical development document archive, without raw private evaluation data.

## Next validation work

1. Expand independent stage fixtures beyond two or three controlled cases. Add externally reviewed labels and representative real excerpts with permission.
2. Include Gemini 3.8 and other account-accessible candidates in the same per-step protocol; do not promote or exclude a family from old mixed tests.
3. Run a fresh online integration test of the standalone package and split selection/assembly. The extra assembly call changes total latency.
4. Re-run large-batch quality, fallback and throughput measurements using available original long-session logs. Old 25/47/99-turn source logs are unavailable; database snapshots cannot validate reconstruction fidelity.
5. Measure context volume versus quality as irrelevant branches grow, with fixed evidence and strong non-tree baselines.
6. Audit scoped constraints, old-feedback routing, topology errors and cross-branch dependencies under sustained interaction.

## Engineering limitations to address deliberately

- Dense recall is a full index scan; no ANN or hierarchical index acceleration is claimed.
- Head/tail extraction is lossy, and framing only sees bounded evidence.
- Incremental append works, but arbitrary edits/removals of finalized history require explicit rebuilding.
- Legacy database/cache migration is intentionally not automatic.
- Source adapter assumptions may break as agent log formats evolve.
- Model-output validation is incomplete for adversarial input; prompt injection and comprehensive redaction remain open.
- Context bundles are returned by a CLI/API; no runtime integration automatically frees another agent from its full history.
- CLI operations remain largely synchronous; model calls are intentionally serial.

## Deferred product scope

- More agent adapters and cross-agent interoperability.
- Multi-device synchronization and identity reconciliation.
- Team permissions and encrypted storage.
- A production editor/runtime integration and active-context paging policy.

## Publication gate

No public release until code ownership/publication rights and a license are confirmed, privacy review passes, installation works without the originating application, and documentation accurately separates measured results from future goals.
