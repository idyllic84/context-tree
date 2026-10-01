# Independent evaluation and model selection

## Principle

Each step has a different job. Select the model best suited to that job, then test the composition separately. A final answer cannot show whether an upstream extraction missed a constraint or whether a later model compensated for an incorrect tree.

For every comparison:

1. Freeze the stage input, including its upstream state.
2. Specify expected intermediate properties before inspecting model outputs.
3. Give all candidates exactly that input and the same output contract.
4. Score quality, invalid operations and harmful changes locally.
5. Compare latency and usage only among sufficiently correct candidates.
6. Keep end-to-end success and latency as integration checks, not stage rankings.

## Stage objectives

| Step | Quality gates | Secondary trade-offs |
|---|---|---|
| Ingest | correct user/response/tool ownership; completed vs pending; source identity | parsing speed, format coverage |
| Extract | explicit facts, acts, prior-response targets, negation and scope | throughput, output size |
| Tree | valid mutations, parentage, independent goals, unit ownership, narrow scope | latency, unnecessary structure |
| Review | repair planted structural faults; preserve correct branches | false changes, conservative stopping |
| Reflexion | evidence supports removal/addition/move; no destructive false edits | repair recall, cost |
| Framing | faithful source content, identifiers/numbers, rejection and acceptance, per-unit attribution | concise output, language fidelity, latency |
| Emit/resolve/index | stable source identity and literal provenance; no invented relationships | write cost and index size |
| Recall/branches | relevant candidates; scope isolation; coherent topology without conflating same-name work | recall cost, irrelevant context |
| Select | valid next action for a frozen state; expand missing evidence; do not drop needed branches | unnecessary actions and latency |
| Context | sufficient supplied facts; exclude noise; preserve separate implementations; cite real nodes | active-context size and latency |

A valid `expand` is not a failed answer. A `done` action with fluent prose does not excuse selecting the wrong branch. Context assembly is evaluated with evidence already fixed; it does not get credit for upstream recall.

## Included evaluator

The seven model-backed stages include **15 unique controlled cases** in their own `evaluate.py` modules. They are synthetic and assistant-authored, with executable assertions and subsequent semantic inspection. They are **not independently human-annotated ground truth**, a representative corpus or a proof of general performance.

Pure-code stages expose their own offline checks. Their success should not be converted into an LLM ranking. Embedding-model selection and broad entity-resolution quality are not covered by the current screen.

```sh
context-tree-benchmark --offline-check
python -m context_tree.stages.reflexion.evaluate --offline-check
mkdir -p artifacts
context-tree-benchmark --allow-network --stages extract tree \
  --models AVAILABLE_MODEL:SUPPORTED_EFFORT \
  --request-limit 20 --output artifacts/comparison.json
```

Each record saves the stage, case, input hash, protocol identity, raw response, checks, stage metrics, wall time, actual request count and available token usage. Keep these files private. No dollar-cost comparison is produced without trustworthy pricing.

## Recorded 2026-10-01 screening

The final pre-migration independent screen made 120 serial requests: 75 initial comparisons across five candidates and 45 repeat comparisons across three. Most stages had two distinct cases; selection had three. The following are provisional choices, not general accuracy estimates:

| Stage | Provisional choice | Local gates | Median call time |
|---|---|---:|---:|
| Extract | GPT-5.6 Sol Fast, low | 4/4 evaluations, 2 cases | 4.58 s |
| Tree | Grok 4.6, low | 4/4 evaluations, 2 cases | 13.89 s |
| Review | Gemini 3.6 Flash, minimal | 4/4 evaluations, 2 cases | 1.27 s |
| Reflexion | GPT-5.6 Sol Fast, low | 4/4 evaluations, 2 cases | 2.65 s |
| Framing | GPT-5.6 Sol Fast, low | 4/4 evaluations, 2 cases | 2.87 s |
| Select | Gemini 3.6 Flash, minimal | 6/6 evaluations, 3 states | 1.32 s |
| Context | GPT-5.6 Sol Fast, low | 4/4 evaluations, 2 cases | 2.17 s |

Reasons for the differences included omission of an explicitly unchanged earlier plan during extraction, over-broad goal grouping, confusing a contradictory claim with a relocation, language switching/length issues during framing, and omission of a required function name during assembly. These observations apply to the tested inputs and settings only.

Gemini 3.8 Flash was not included in this independent-stage screen. Earlier small measurements used different prompts/settings and cannot establish that it is worse. Grok 4.7 and GPT-6.1 had fewer repeat observations. Current account availability and new model versions must be checked before reuse.

### Scoring corrections

Earlier scoring mistakenly treated reaffirmation as invalid when emitted as `affirm`, and missed equivalent Chinese content when checking English words. Outputs were rescored without new model calls; original outputs and initial scores were retained privately. A prior loop evaluator also confused legitimate extra retrieval rounds with bad retrieval and exposed inconsistent citation IDs. Those results must not be used as independent stage evidence.

Regex coverage is only an aid. A response can contain the expected word while reversing its meaning. Inspect negation, source support, numeric units, scope and references. Clean-tree/no-change cases are essential to detect over-correction.

## What remains unproven

- Accuracy on long, noisy, real development histories and branch switches.
- Quality versus active-context budget with fixed evidence across competing structures.
- Whether task topology contributes beyond extraction, file links and model effort.
- New split selection/assembly pipeline's live end-to-end latency and total cost.
- Large-batch performance after the schema changes; old raw test logs are missing.
- Independent replication and stronger human-annotated gold.

Use the bundled checks to develop safely, not to declare the research hypothesis solved.
