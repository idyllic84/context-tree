# Context Tree development rules

The project history (earlier designs, research rounds, superseded approaches) is summarized in `docs/evolution.md`, a record
rather than current instructions; the archives themselves were removed on 2026-11-23.

## Documents

- Design (authoritative): `docs/ctm-concept-model.md`. Goals, metrics, method and the block-wise optimization plan:
  `docs/goals-and-method.md`. Implementation status, evaluation results and current model choices:
  `docs/implementation-status.md`; block evaluations: `docs/block-evaluation.md`. Map: `docs/README.md`.
- Mechanisms are described in the concept model, not here. Replace rather than append in design documents; record superseded approaches
  and adverse results in `docs/evolution.md` and repair links.

## Design principles

- CTM is the single assistant between the user and executing agents: one continuous conversation; long-term memory is a task tree and
  versioned documents, written as each message arrives.
- Work-oriented, not topic-oriented: purposes and actual work define Goals and Tasks; the same object or topic does not make the same
  work. Structure is judged in context, not by mechanical rules.
- Authority: the user's words and UI edits over CTM's inference over maintenance. Executor reports never replace what the user stated.
  Every item keeps its time and what replaced it; only current items are delivered.
- Executors get small but sufficient context. The goal is the user's own words: no paraphrase, no added requirements, no tightening.
  Do not create unrequested obligations; unknown is neither done nor failed; keep reported and verified apart.
- Whose business: executors do only the user's work and get only the user's words and context. CTM's own business (its memory,
  its local ctm.md records, its proposals) and words addressed to CTM stay with CTM; never add them to an executor's input.
- Ask or act by reversibility: irreversible actions need the user's explicit authorization.
- Few steps: a mechanism goes into a call already on the path (its prompt and inputs) rather than a new step. A judgment not
  needed every time is a signal in a main prompt's output that triggers one more call only then; do not overload one prompt.
  Code stores, delivers, applies the LLM's signals and enforces safety limits; it does not make semantic judgments.
- Semantic matching (work, object, referent) uses LLM understanding or embeddings, never literal, keyword or regex fallbacks.
  Identifiers the user writes may propose candidates when identical or differing by a typo; the decision stays with the LLM.

## Working method

- Decide design and evaluation questions from the project's goals, using reasoning and web research when unsure; do not ask the user
  to decide. Engage critically with the user's proposals. Report in Chinese with conclusions and reasons.
- Reason first: walk through scenarios looking for missing information, ambiguous judgments and conflicting rules, and re-run the key
  scenarios after each change. Keep layers apart (world model, concepts, mechanisms, evaluation).
- Optimize CTM block by block (blocks in `docs/goals-and-method.md`): each block has its own inputs, metric and test set, is
  tested with reference inputs from upstream blocks, and changes one thing at a time; check the whole flow end to end occasionally.
- Run experiments only for what reasoning cannot settle; state the question and which concept a result would change. Keep each run
  under 30 minutes (split or sample larger ones) and report waiting time honestly.
- Test data must match the target scenario (one assistant, parallel work, no sessions). Historical session records serve for habits,
  frequencies and counterexamples, not as direct tests. Measure each revision on data not used before. Labels come from independent
  annotators' consensus and from hindsight behavior (what the user did next); no user spot-checks.
- Prompts explain what each judgment is used for, what each error costs and what to ask oneself; never use sentences from test data
  as examples. A prompt is not a list of rules: it describes the situation, what the relations mean and how they are used, gives the
  information the analysis needs, and asks the model to analyse the relations between the nodes in context before it decides (the
  analysis comes first in the output). A rule added to stop one observed error is code in disguise and fails on the next case.
- Models are chosen per role by measurement (current choices in `docs/implementation-status.md`). No sol models in CTM; evaluation annotators
  and judges are independent of the systems under test, with sol used only as a judge when the user asks. Token budgets follow each
  model's real limits and count the complete call.

## Language

- Code, comments, prompts, the page and the documents are in English; text the models write for the user (titles, summaries,
  answers, memory statements) follows the user's language.

## Boundaries

- Launch subprocesses and sub-agents windowless.
- Private data (transcripts, source IDs, real prompts, credentials, outputs) stays outside Git. Archive databases are read-only;
  research artifacts are cold-archived only with a hash-verified restore manifest.
- Runtime integration (pi, real sessions) and changes to production providers or credentials need the user's explicit approval.
  Do not touch other projects.

## Code status

- `src/context_tree/ctm2/` is the mainline implementation of the concept model; `src/context_tree/pilot/` runs it as a local page
  with pi sessions as executors. Offline tests are `tests/test_ctm2_*.py` and `tests/test_pilot*.py`. Which concept items and user
  requirements are wired into the running flow, and how each was evaluated, is the table in `docs/implementation-status.md`;
  keep it current. The code keeps only the current version of each flow and prompt, plus at most one candidate under evaluation
  (passed in as a parameter, not a flag); earlier versions and options not adopted live in the evaluation records and version
  history. The earlier packages were removed on 2026-11-23, the first message flow of `ctm2` on 2026-11-25.
