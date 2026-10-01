# Historical development archive

These are the ten original development documents, preserved from the working tree during standalone extraction. Their historical filenames and relative links are retained. Personal machine paths and session identifiers may be consistently anonymized; this is not a verbatim private-data archive.

**Current authority:** [project goals](../goals.md), [architecture](../architecture.md), [stage contracts](../stages.md), [evaluation](../evaluation.md), and [roadmap](../roadmap.md). Historical DRAFT markers, unchecked tasks, implementation paths and timings are not the current implementation status.

## Reading order

1. [Context-tree design](context-tree-design.md): task evolution, branching, scope and pruning motivation.
2. [Original Companion framing](claude-code-companion.md): early product context.
3. [Technical proposal](companion-technical.md) and [specification](companion-spec.md): early system designs.
4. [V2 design](companion-v2-design.md): dialogue units and task hierarchy.
5. [V2-B design](companion-v2b-design.md): decision-centered framing.
6. [Tree-native C design](companion-v2b-v3-design.md): evolving extraction and structural retrieval ideas; early sections and later additions can disagree.
7. [Research log](companion-v2-research-log.md): experiments, reversals and outstanding questions.
8. [Demo record](companion-demo.md): dated observations, not a regression suite.
9. [Paper outline](companion-paper-outline.md): proposed claims, not established contributions.

## Important qualifications

- The original work included different codebases and application integration. Their paths are historical; the active standalone source is under `src/context_tree/stages/`.
- Early “user messages only,” “no suitable coding benchmark,” single-call extraction and separate tree/graph-route statements were superseded.
- Some references are incorrect or overextended. Read [citation corrections](../research.md) before using them.
- Performance tables can mix measured values, estimates and uncompleted trials. Do not combine them into one current benchmark.
- [Original evaluation logs](eval-logs/README.md) are deliberately excluded because they can contain private conversation content. Public reproducibility is limited to the synthetic fixtures supplied with the code.
- The full source documents remain in the originating workspace. This archive preserves technical history without granting publication rights; see [license status](../../LICENSE-STATUS.md).
