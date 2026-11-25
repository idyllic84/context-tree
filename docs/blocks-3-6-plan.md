# Independent Evaluation and Optimization Plan for Blocks 3–6 (2026-11-19)

The processing flow is divided into 8 blocks (1 delivery, 2 tree organization, 3 memory write, 4 execution context, 5 executor interaction, 6 work status and lifecycle, 7 answering queries, 8 communication with the user).
Blocks 1 and 2 can already be evaluated independently; the self-assessment of blocks 3–6 (2026-11-19) is that the mechanisms are broadly usable, but the evaluation methods, labels, or boundaries are insufficient for independent optimization. This plan first establishes the evaluations, then optimizes each block.
The results are written into Section 7 of the [implementation plan](ctm-implementation-plan.md), and the block divisions are written into Section 3.4 of [Goals and Method](goals-and-method.md).

## Common Rules

- **Paired**: The groups being compared face the same set of items. A judge first lists the items (information needed, content to be restated, constraints that should be present) **without seeing the outputs under test**, then judges each group item by item.
  The practice of having a judge list items while looking at and judging the outputs under test (`fresh`, `restate` on 2026-11-18) is no longer used for comparisons.
- **Judges**: opus and terra; only items on which both agree count. Labels from a single judge (including grok in earlier evaluations) are for reference only and are re-annotated when used.
- **Data**: The user's data from the week of 11-13 (w1113) is used for development and diagnosis; the user's subsequent new data (`auto_eval.py daily`) and unused public data are used for testing; each modification is measured on unused data.
- **Metrics tied to consequences**: Besides “was it recorded, was it provided,” also check whether it reached the executor it should reach, whether it was carried into unrelated work, and whether it helped the executor act correctly.

## Redivision of Blocks and Evaluations (2026-11-19, supersedes the 8 blocks at the start of this document)

Divide blocks by judgment, with upstream blocks providing reference inputs; see [Goals and Method](goals-and-method.md) 3.4. The following previous evaluations depend on other blocks, so they **are now used only for monitoring**. Their conclusions await retesting with reference inputs:

| Previous evaluation | Blocks involved | Treatment |
|---|---|---|
| Tree organization measured by constraint delivery (`cover`, `cons`) | Memory attachment level, context assembly | Block 2 switches to precision and recall of relationship judgments |
| Execution context (`fresh_pair`, `fresh_prog`, `fresh_where`) on replayed memory | Delivery, tree, memory, progress summaries | Block 4 retested on frozen reference memory; the 32,000 budget and “16% under other Goals” await confirmation |
| Judged too early (`status_hind`) | Delivery | Block 7 switches to annotated subsequent events |
| Whether a successor was linked (`link_check`) | Delivery (references are established by delivery) | Moved into block 2 |
| Session selection (`session_choice`) | Delivery | Switches to annotated destinations |

Memory write coverage (`reach_b2`) uses the reference tree and the data model's inheritance rules and does not depend on other blocks, so it is retained.

### New task order
1. Block 4: Build frozen reference memory and retest the conclusions about execution context.
2. Block 2: Have two judges annotate relationships between pairs of work items; measure the precision and recall of the new work placements given by delivery, structure judgments, Goals, and references.

## Independent Evaluation under the New Block Division (2026-11-19)

**Block 4, execution context, on frozen reference memory** (`blk4.py run|where <win>`: block A's reference memory—delivery and tree construction according to annotations, and the original exchanges—plus block B2's frozen V6 items and frozen V4 summaries within the window;
a test point is the first appearance of a work item in a real session that already has prior messages; needed information is listed only from the real session and accepted by both judges). Four windows, 61 points, 232 items, 191 agreed items:
**present 57%, partial 34%, absent 9%**, with a median context of about 10,000 characters. Of the gap from the 31–44% measured on replayed memory, most came from upstream (misdelivery, tree, memory), not assembly.
- Contexts assembled with budgets of 24,000 and 32,000 were **identical word for word** (both were well below budget); the two groups' “present” judgments differed by 6 items—this is the variation from judging the same text twice. Differences smaller than this do not count. The previous conclusion to “change the budget to 32,000” cannot be demonstrated on reference memory; 32,000 is retained (no worse, useful on replayed memory).
- Sources of the remaining items (agreed by both judges): 25 from executor replies in sibling work, 23 from replies in other work (neither sibling nor parent/child), 5 from parent/child replies, 6 from the user's words, 23 unclear; 0 from the same work item.
  “Other work” depends on references between work items (block 2). The reference tree has no references, so this is not attributable to block 4.
- Fill the budget by value (`context.VALUE_FILL`: put sibling exchanges and earlier exchanges in the current task into the budget according to their relevance to the message divided by length): changed only 12 of the 61 contexts; in these 12, “present” was 34／37／41 (24,000／32,000／fill, with identical text in the first two groups),
  the gain was on the same scale as the variation, and “partial” was unchanged. **Not adopted**—most new work has no earlier sibling exchanges to add.

- Do not truncate original exchanges (`context.NO_CLIP` for diagnosis, budget 60,000): across four windows, “present” 115→124, “partial” 61→52, with the median context only a few hundred characters longer—truncation has some effect, but is not the main cause of “partial”; most details are not in the exchanges handed to the executor. The truncation length is not changed for now.

**Block 2, work relationships, new work placements given by delivery** (`blk2.py placements <version>`: placements on block A's reference memory that delivery judged to be new work; two judges decide item by item whether the recorded relationships are true, and list omitted “component／next step” relationships):

| | Parent: given／true／false／disagreement | Goal | Previous step | Omitted relationships |
|---|---|---|---|---|
| V13 | 41／34／1／6 | 54／53／0／1 | 43／22／**15**／6 | 2 |
| **V14** | 42／34／4／4 | 52／47／1／4 | 19／16／**1**／2 | 4 |

Cross-task references (`blk2.py uses <version>`, two judges decide item by item whether the recorded uses are true, and list work that the new work really needs to use but did not record): V14 recorded 53 items, 43 true, 7 false, 3 disagreements;
but among 52 new work items, 26 had omissions identified by both judges, 47 omissions in total—this is precisely the source of the missing information in block 4 “from other work.” V14 described only the cost of writing too many (distracting the executor); **V15** describes both costs accurately and first considers which existing conclusions the new work builds on. It is set as the default: 76 items recorded, 57 true, 10 false, 9 disagreements (precision about 85%, the same as V14);
omissions identified by both judges fell from 47→35 (26→21 new work items); block A's continuation of current work 0.98→0.96, other existing work 0.90→0.87 (variation between two runs of the same instructions is about ±0.02), side question handling about other work 0.63→0.67.

A previous step (after) establishes a sequential dependency: its result is handed to the new work, the executor treats it as “the previous step just completed” and examines it in the most detail, and if it is unfinished, the new work is considered to be waiting. V13 had only a one-sentence definition, so recently performed work on a similar topic was often recorded as a previous step.
**Delivery V14** describes this use and the respective costs of incorrect and omitted entries, and is set as the default; block A's categories are on par with V13 (handling of continuation of current work 0.91→0.93, side questions about other work 0.73→0.76, new work identification 0.85→0.82).

**Block 3 facts (first evaluation)** (`blk3facts.py annotate|gold|score`: four windows, two judges independently annotate specific facts stated by the user that need to be known to continue work later—environments and addresses, locations, identifiers, practices, statuses, deadlines;
executor replies are not annotated; according to the concept model, the executor writes those into documents; items annotated by both judges are the ground truth): of 66 items, V6 recorded 10 as facts (15%), 15 as other classes (constraints, decisions), and **did not record 41 (62%)**.
The unrecorded items are needed by whoever takes over: the branch to submit to, locations of test audio and key files, how to write a query, that a PR had been merged, that an environment had been redeployed. V6 has only a one-sentence definition of facts and does not say who receives them or what omissions cost;
V9 adds the use and costs (hand them to whoever takes over and cannot see this conversation, and also use them to answer queries; omissions require rediscovery or asking the user to repeat them; record volatile status with a timestamp): recorded as facts 10→14, unrecorded 41→37,
constraint and decision recall unchanged, precision rose or fell in different cases, within the variation. **Not adopted**. Most unrecorded facts are embedded in one-time requests (“submit to a branch and merge main”), and the whole sentence is discarded as a one-time matter.
But the user's original words are preserved in full and passed on (original text of the latest 6 turns of the same work, sibling exchanges, original text retrieved for queries). The actual loss from omitted facts depends on block 4's measurement of “was the needed information provided” (92% structurally reachable);
adding a dedicated extraction call for an intermediate metric, and redundantly saving things that can already be passed on, is not justified in principle.

**Block 9 relay (first evaluation, from the user's side)**: The relay shown to the user by the pilot after execution is complete is assembled by code from several fields of the progress summary (`pilot.app._relay_text`), with no separate model judgment—the content is block 5's output,
with the reader changed to the user; block 6 decides which stops enter the conversation. Evaluated separately from the user's side (`blk9relay.py run 60`: replay of V4 summaries from two data sets, d1119 and d1120; two judges decide whether the result can be understood and responded to from the relay alone,
and whether the user's next message used details present in the original reply but absent from the relay): of 60 segments, both judges agreed that 58 were “sufficient”; both judges agreed on 0 segments where the user subsequently relied on details missing from the relay (2 disagreements).
The median relay was about 1,000 characters, the original reply about 1,400 characters: not much compression; the value lies in the fixed fields. In real use, the pilot records how often users open the original reply, which can directly measure whether the relay is sufficient.

**Block 6 formal completion check (first evaluation)** (`blk6comp.py run 60`: 60 executor replies from four sets of user data; two judges use the same standard to decide whether they are formally complete, with the user's next message in the same session indicating missing items as the subsequent evidence;
the system is `control.check_completion` (flash), using the user's request as the contract): of 53 items on which both judges agreed, 50 were judged correctly (94%); 2 incomplete replies were let through, and 1 complete reply was blocked; in both cases where the user subsequently pointed out something missing, the check had already marked the reply incomplete. Meets expectations.

**Block 7 status, on reference inputs** (`blk4.status_ref <win>`: reference memory with Goals, frozen summaries, 12 hours after the window ends; two judges annotate status from the records, and maintenance V11 judges on a copy;
subsequent evidence is the annotated follow-up—whether the work item received another message from the user afterward): across four windows, 73 items on which both judges agreed, maintenance judged 63 correctly (86%); 5 should have ended but did not, and 5 were judged ended but had not ended;
of those judged ended, the user returned to 4 within three days (reopened according to the concept model, at low cost). Meets expectations.

**Block 6 execution control** (E7, 190 agreed annotations, flash V2, 0.82): the main confusion is judging requests for information or decisions as “no question asked” (relayed to the user as completion reports; the user can still answer, so the cost is low);
the risk is 5 cases where requests for permission were judged as instructions to continue the executor (mostly already authorized in the user's original words and allowed by the rules). Close to usable; analytical V3 previously performed worse, so no change.

**Other block 2 judgments** (`blk2.py goals|structure earlyg`, block A's reference memory, two judges decide item by item whether the recorded relationships are true):
- Goal assignment: 59 instances of “work serves this Goal” under 11 Goals, 49 true, 2 false, 8 disagreements (96% true among the 51 agreed items), meeting expectations.
- Structure judgment: run at 8 Goal levels, with 14 groupings, 8 true, 1 false, 5 disagreements; both judges identified 1 instance that should have been grouped but was not. There were few groupings, and those made were mostly true.

**Connection between block 4 and block 2** (the reference group in `blk4.py`: add ideal references to the reference memory—work identified by both judges as the source of missing information that is neither a sibling nor on the path):
across four windows, “present” 115→**135**, “absent” 15→10 (variation about 6 items). When references are correct, current assembly can recover a large portion; the remaining block 4 gap depends mainly on block 2's reference recall (V15 still has 35 omissions).
- Provide referenced work in detail like sibling cards (`context.USED_DETAIL`: latest three progress entries including pending items and failures, current decisions, environment): across three windows, “present” 108→113, within the variation. **Not adopted**—recent conclusions are mostly already in progress summaries.
- Among references still omitted by V15, some work appears only in the local tree visible to delivery, while the instructions permit only IDs of candidates, research, and queries. **Delivery V16** permits the local tree: true 57→60, but omissions identified by both judges 35→45, with block A's categories rising or falling,
  within the variation. **Not adopted**. Asking delivery to consider item by item “whose work will be needed” does not improve recall.
- Retrieve potentially relevant conclusions from elsewhere during assembly (`context.RELATED_WORKS`): across four windows, “present” 115→125, **withdrawn, not adopted**. It selects other work for the context by similarity to the message, bypassing work relationships recorded in the tree (selecting by topic rather than by work), makes relevance judgments in code, and masks the problem of omitted references in block 2. The gap must be resolved on principle in block 2 (references) and in concept model 5.2, “the executor asks CTM for results of other tasks.”

**What is missing “from other work” and which route it should take** (first distinguish the kinds of information, then decide which block to change):
- Classification (`blk4.py classify_other`, agreement between two people): among missing information from work that is neither on the path nor a sibling in the reference memory, 18 items were “that work’s conclusion, on which the new work builds,” 7 were “reusable practices or environment,” and 3 had disagreements.
- The 18 “conclusion” items are almost all from the previous step or the step before that in the same piece of work (“submitted in the previous turn,” “the six issues in the previous turn’s review report,” “the previous turn’s benchmark results”): the user advances the same piece of work step by step in one session, while the reference tree places these steps on different branches.
  Under concept 3.4, successive steps are siblings under the same parent, so the executor sees the scene of each step during assembly—this is the responsibility of block 2 structure, not references or retrieval.
- Block 2’s recall on these actual dependencies (`blk2.py seq_links`: whether delivery V15 delivers the message into that work, or the new work follows it, is placed under it, is a sibling, or references it): 8 of 18 linked.
  Most of those not linked were delivered into the immediately preceding step, while the needed information was in an earlier step: what is missing is the organization of the steps of the same piece of work under one parent.
- Thus, a substantial portion of the “from other work” gap measured by block 4 on the reference memory comes from the reference structure itself, not an assembly error; the 7 “practices or environment” items should, under the concept, be written down by block 3 (object constraints, environment facts) and block 5 (practice documents) and delivered by object, and should be evaluated separately.
- The reference tree itself is fragmented: in the example above, the steps are split across two branches, “align leading and trailing silence handling logic” and “evaluate connection pool / implement connection pool changes,” while several reviews are attached directly to the root. This does not meet the rule that “successive steps are siblings under the same parent” (early annotation, when the tree model had not yet been decided).
- **The block 4 metric is therefore changed to count only structurally reachable information** (`blk4.py reachable`: sources agreed on by two people are on the new work’s path or among its siblings; two items both attached directly to the root do not count as siblings—
  the dev and test reference memories have no Goal, and the work items under the root are unrelated): across four windows, **present 57 (92%), partial 5, absent 0**; from other branches, present 33 (42%), partial 34, absent 11, counted as structural.
  Block 4 is already close to the upper limit on reachable information. The gap is in the structure: work on the same thing, with the same goal, is separated in the tree.
- **After adding Goals to the reference memory** (`blockA.py build dev|test 1`: Goal judgment output frozen as reference input; the `g` group in `blk4.py`):

| | Without Goal present／partial／absent | With Goal present／partial／absent | Median context |
|---|---|---|---|
| dev1 | 31／13／7 | 36／10／0 | 9.8k→20.9k |
| dev2 | 26／9／2 | 30／4／0 | 7.1k→21.1k |
| test1 | 13／9／2 | 17／7／0 | 9.5k→21.7k |
| test3 | 45／30／4 | 49／26／3 | 10.4k→23.8k |
| Total | 115／61／15 | **132／47／3** | about 10k→about 22k |

  Work with the same goal becomes siblings under the same Goal, and assembly delivers each work item’s scene to the others: the gap is indeed in the structure, and the existing Goal judgment fills most of it. This was previously missing because the reference memory had no Goal (an evaluation defect); the system already had the Goal layer.
  The cost is that context roughly doubles (still within the 32k budget). What remains is within Goals: steps of the same piece of work are under the same Goal but scattered under different parents (test3), requiring block 2’s structure judgment or moves during maintenance.
- The remaining gap within a Goal (that piece of work in test3): several reviews are attached directly under a Goal with 53 work items. The connection pool and “align leading and trailing silence handling” are two parallel work items under the same Goal, and the reviews use conclusions from both—
  this is a use for references (between parallel work items), not entirely a structural error. At delivery, this dependency is implicit (the user only says “review using skill”): in one case the source work is among the candidates but no reference is written (judgment); in the other cases it is not among the candidates (block 1’s candidates).
  The concept’s fallback channel is for the executor to ask and block 8 to answer; with a Goal, the work line searched by block 8 is the entire Goal subtree, which contains the source—replay cannot test whether the executor will ask.
- The 7 practices and environment items: most came from executor responses—under the concept, the executor writes them into documents, but the executor does not write them in replay, so this cannot be tested; the few stated by the user (such as “do not run concurrent tests in a certain test environment”) were not recorded in their source turns,
  and the sources of two items were before the frozen memory window (the reference memory is incomplete). There is also a design question pending discussion: under 3.5, object rules without a directory remain on the work where they were stated and cannot reach other work using the same object; storage has object entries and `involves` relationships,
  so delivery by object makes sense in principle, but there are only one or two pieces of evidence, so leave it unchanged for now.
- Next: run structure judgment at the layer where these dependencies occur and see whether it can group the steps of the same piece of work under one parent (block 2, evaluated independently); also examine delivery’s position judgment when new work is “the next step in the same piece of work.”

**Block 8 answering queries** (probe questions generated from records and scored by two people, independently of other blocks): causes of errors—most of the 7 not-found questions were cases where the record being asked about did not rank in the top 8 retrieved; all 3 wrong answers treated old statements that had been replaced or rejected as current,
and retrieval of an old entry did not include the new entry that replaced it. Two changes (`recall.RECALL_K = 20`; `recall.SHOW_REPLACEMENT`: when a replaced record is retrieved, follow the replacement relationship and include the current one):

| 46 questions | Correct | Not found | Wrong | Partial | Disagreement |
|---|---|---|---|---|---|
| Original (top 8) | 28 | 7 | 3 | 2 | 6 |
| Top 20 | 30 | 5 | 3 | 5 | 3 |
| Include replacement entries | 29 | 6 | 3 | 5 | 3 |
| **Both together (default)** | **33** | 4 | 2 | 3 | 4 |

**Block 8’s remaining errors** (33/46 after retrieving more records and including replacements): for questions asking “has a work item been completed,” retrieval selects by similarity between the question and records, retrieving the original request but not the work item’s status and progress;
rejected statements are treated as current (a rejection is a new decision and does not necessarily have a replacement relationship with the old entry); some constraints and decisions are not retrieved in full. The query knows which work item is being asked about, and its status is in its status and recent progress—
give the work item’s current-state card when answering (`recall.WORK_CARD`: title, status, three most recent progress entries, submitted results), based on structure rather than similarity: questions about status and progress went from 12→14 all correct, not found 4→1,
but wrong 2→4 (two decision questions asking “what was decided at the time”). The card describes the present, while the question asks about the past; after the label was made explicit about its purpose and the test rerun, correct answers were 35 and wrong answers were still 4, with the same two questions. Wrong answers cost more than not found (when not found, the user will follow up or dispatch read-only execution), so **do not adopt** (`WORK_CARD` is off by default). In principle the card should be given only when the question asks “what is the situation now,” but this requires first knowing the question category (one more call or one more signal from delivery). Changing the main flow for two questions is not worthwhile; record it as a direction.

**Delivery input composition and cost** (A block earlyg delivery input averages about 21k characters): candidates 45% (more than half of that is each candidate’s recent results), local tree 30%, recent conversation 12%, Goal list 9%.
The local tree is never mentioned in the delivery instructions; removing it (`blockA.py call ... V15_nolt`) reduces input per delivery from 11.8k→9.1k tokens, but new work identification drops 0.82→0.78, side questions about other work 0.76→0.71 (method 0.67→0.59),
correct placement of new work under a parent 32→25, and correct references 57→52, with omissions rising 35→42—the model implicitly uses it to judge position and references. **Keep it**.

**Block 8 giving a current-state card only when needed**: following the signal principle, change it to add a card and answer again only when the first answer says not found (`recall.CARD_ON_MISS`): 34 correct, 4 wrong—one question asking “what was decided at the time” was not found on the first answer,
then answered wrongly after the card was added. When a historical question is not found, it should say so and dispatch read-only execution to investigate; giving it the “current state” will lead it to fabricate a historical answer. Query instructions V3 have the first answer also indicate whether the question asks “what is the situation now” (`about_now`),
and add cards only for those questions: the model’s judgment was reasonable (21 of 46 questions judged to be asking about the current state), but 33 correct and 3 wrong, comparable to not adding cards (33, 2)—the three changes were one status question from not found→correct, one status question from correct→disagreement,
and that “alias” decision question wrong again. None of the current-state card approaches exceeded the variation, so **adopt none of them** (`WORK_CARD` and `CARD_ON_MISS` off by default, query instructions remain V2).
The question that is consistently answered unreliably: in memory, “do not add an alias in the code for now; write it into the design document” (turn 1270) is the current decision, and retrieval found it; the model used the user’s initial words from turn 1267.
The question asks “what was decided at the time”; both the initial request and the final decision are plausible readings—this is an ambiguity in the question, not a system defect. Most of block 8’s remaining errors are ambiguities of this kind and variation from answering again.

**Block 5 progress summary input and length**: when writing summaries, responses are truncated at 8000 characters, but not one response in the four datasets exceeds 8000 characters (median 1–1.5k, longest under 6k), so truncation never occurred.
Another observation: V4 summaries are about 900–1100 characters, roughly as long as the responses themselves; the original text of recent turns has already been delivered to the executor, so the original text and summary of the same turn appear together. Summaries are useful downstream (coverage 40%→65–70%),
but under concept 3.2, one resolution level should be selected per node according to budget (turns with the original text included do not also need summaries). **Done** (`context.DEDUP_RESOLUTION`, default): in “recent progress” for the current task and its siblings,
when the original text of a turn is included **in full** in context (the response is not empty and neither side has been truncated), its summary is no longer listed; summaries are still listed for turns that were truncated or whose responses were not saved—the first version did not check completeness, and a unit test caught a sibling’s result being dropped because it was only in the summary.
On the reference memory with Goals, “present” 132→143, “absent” 3→3, and median context became slightly shorter (19.9k–24.0k).

**Block 5 dispatch method**: doing new work in the parent’s session (`session: parent`) occurred only 19 times among 161 new work items in three A block datasets; the cost of opening a new session is already covered by block 4 (92% of structurally reachable information is delivered), so the impact is small and no separate evaluation is needed.

**Daily evaluation d1120-1042** (50 user messages from 11-19 14:21–11-20 10:41, 5 sessions, all new defaults: delivery V15, progress summary V4, replacement comparison V5, query retrieval of 20 entries with replacements, budget 32k, replay simulation selected):
42 of 45 adjacent pairs in the same session were delivered to the same work item, with no incorrect judgments; 5.16 calls per message, 23.1k input tokens, median 45 seconds (more queries: 0.36 per message).
**Constraint arrival exposed contamination in the evaluation chain**: 2 new executors received 118 constraints, all irrelevant, all “object rules” on the root—written in the user’s week of 11-13, from r4 (for comparison, a rejected old configuration was used throughout:
object rules without a directory were placed on the root); daily evaluations continued from r4’s memory, and these entries remained. The user’s actual `D:/ctm` has no such entries. Migrate according to the current rule (3.5)
(`auto_eval.py migrate_root_object_rules`: attach root object rules back to the work to which the original message in that turn was delivered, and record a migration event), all 58 entries attached back; this constraint check is invalidated, and the next daily evaluation will examine the results after migration.

**Interface added through assembly walkthrough: items left for the user in a response become numbered pending items** (S2, S8; concept 1.2 “every message can be referred to, pending items are numbered and identify their owning task,” 5.2 item 6).
Previously, the display written into memory after execution was completed had only one line, “Completed: …”; the items requiring the user’s decision in the relay appeared only in the pilot interface. Now (`pipeline.OPEN_ITEMS`, default): when a turn’s response is not escalated to the user by the control layer,
each `open` item in the progress summary becomes a pending item (attached to that work) and is shown with a number; a new response for the same work replaces the previous batch; the pilot’s relay lists them with the same numbers.
A turn escalated by the control layer no longer generates them again—the first version lacked this rule, and a unit test caught the same question appearing twice, with approval resolving only one.
Evaluation (`blk3pending.py run 40`: messages responding to items listed in the previous response across four datasets, selected by terra; frozen V4 summaries provide pending items; decisions marked by agreement between two people serve as the ground truth):
29 messages, 75 decisions, correctly recorded in memory: 62 without pending items, 66 with them. On the delivery side (when several work items are waiting for the user at once, which one “OK” or “the second one” refers to), replay cannot test this.

**Block 1’s remaining errors by purpose (2026-11-20)**: on earlyg, V15 correctly delivered 37 of 49 side questions about another work item, and attached 10 of 55 that should have been created as new.
- The purpose of a side question is to answer it; retrieval for answering from memory covers the entire subtree under the selected work’s topmost ancestor (`recall.line_of`), so if it lands in the same Goal, the answer is unaffected. It only affects where the query record is attached and which session read-only execution branches from.
  By this measure: earlyg 48/49, dev 19/21, test 19/23 (the dev and test reference memories have no Goal, so the scope is the root work subtree, which is stricter). Most errors select a parent or child in the same group of work, or a sibling that just reported results.
- Of the 32 items that should have been created as new but were attached (total across three datasets), 28 were attached to the same piece of work (parent work, previous step, or sibling): implementation after analysis, cause investigation after testing, additions after rechecking. The cost of attaching them is that one work item mixes several steps, while the executor remains in the original scene;
  conversely, creating new work when it should have been attached makes the executor lose the scene, at greater cost. The delivery bias (18% attached when new work should have been created, 3% created as new when it should have been attached) is consistent with this asymmetry. The other 4 were attached elsewhere; the two in earlyg require looking at later messages to distinguish.
- Conclusion: do not change the delivery instructions. Several steps mixed in one work item can be split during structural review in maintenance (concept 5.2: splitting is allowed; the new executor brings along the parent work and siblings).

**Object constraints: errors exposed by a real pilot trial (2026-11-23/24)**. “Add a region to the configuration this time and reuse the existing endpoint” was recorded as a long-term object constraint on the configuration file. The executor wrote it into `ctm.md` and included it in a PR with a commit.
- Design problem (aligned with the user on 11-24): CTM had no action channel of its own. Writing object rules was slipped into the input to an executor working in the same directory (`ctm.md` thus entered the PR with the commit for that work).
  Drafting `ctm.md` was also slipped into the input to the project's first executor. Conversely, “remember globally...” spoken by the user to CTM had no destination and was delivered to the executor, which modified its own global configuration.
  In addition, a judgment that was itself uncertain (an object rule or a change for this occasion) was directly connected to the action of “writing into the user's code.”
- Correction (concept 1.1 “Each Has Its Own Business,” 3.5, 5.1): Executors only do the user's work; CTM's business is no longer slipped into their input. CTM itself writes, modifies, and deletes `ctm.md` (`objectfiles`, kept only on the local machine).
  CTM proposes source comments as numbered pending items. After the user responds, they are handed to the executor for that work along with the user's original words. Words addressed to CTM go to delivery's `memory` destination (V17, evaluation below).
  On 11-24 I briefly removed source comments altogether, going beyond the user's rule, which concerned only `ctm.md`. I restored them after the user pointed this out. The aligned approach is to propose them and let the user decide.
- Judgment attempt (`research/blk3obj`, historical messages imported from D:\ctm, not used to tune the memory instructions; annotations agreed by two people, with annotators unaware of the version):
  V10 added a self-question to the object constraint instructions: “After it is done, does the object itself already reflect it?” On 200 messages, “just the content of this change” fell from 13→3, but “an agreement to keep following in the future” also fell from 12→3.
  Once implemented, an agreement is likewise reflected in the code. This self-question was wrong, and agreements were instead recorded as decisions or task constraints. V11 instead asked, “If someone later changes this object for another need, would they violate it without knowing?”
  On another 200 unused messages: V6 agreements 13, change content 12; V11 agreements 7, change content 6. Both were halved together, and discrimination did not improve (52% versus 54% recorded correctly). Neither is adopted.
- Trade-off: After the design correction, the cost of recording one extra “change content” item is one extra item in the local `ctm.md` (the executor stops and asks once when someone wants to change it later) and a proposal that can be ignored.
  If an agreement is missed, other work will later violate it unknowingly. The costs are asymmetric. V6 tends to record more, so V6 is retained. When judgment cannot be made accurately, make the cost of a wrong judgment small and visible, rather than tightening the judgment.

**Block 1: Words addressed to CTM (delivery V17, 2026-11-24, `research/blk1mem`)**. V17 adds the `memory` destination: when a message is only a memory operation directed at CTM (remember, forget, or change something already remembered) or an adjustment to CTM's own way of doing things,
it is not delivered to the executor. Step 5 records it, and the conversation displays an expanded view of what was recorded.
- Data: historical messages imported from D:\ctm, 700 selected at random (not used to tune the delivery instructions). After initial screening by flash, two judges annotated them independently. The 109 agreed items were: work 99, “addressed only to CTM” 8, mixed 2.
- Work messages misclassified as `memory` (the matter was not delivered, the most costly error): V17 0/99, V15 0/99. All 8 destination changes were between “continue work” and “side question” (variation from rerunning), unrelated to `memory`.
- Both versions delivered all 8 items “addressed only to CTM” to the current work. Examined one by one, they were rules for work in progress (for example, stop using a particular local service, wait for the user's review before pushing). The executor needed them at that moment, so delivering them was correct.
  My annotation definition was too broad: what belongs to CTM is the memory operation directed at CTM, not the rule itself (the rule is recorded by memory as usual and relayed as a current item to the relevant executors).
- Only one actual memory operation was found in all the historical messages (the one that triggered this issue: “Remember globally, don't check in ctm.md”): V17 classified it as `memory`, while V15 delivered it to the executor.
  Both versions correctly delivered two superficially similar messages (asking the executor to document a test method, and to install a tool after confirmation) to the executor.
- Adopt V17: it adds a destination already present in the concept but missing from the implementation (1.1, S15), and no harm was measured. The benefit was seen only on the one message that triggered the issue, so it needs to be watched in pilot trials (destinations and redeliveries in the report).

**Block 3: Withdrawal (memory V12＋replacement V6, 2026-11-24, `research/blk3wd`)**. In a real pilot trial, the user said of a rule, “That's not right, delete it.” It was recorded as “rejected: delete this rule,”
and then replaced another user requirement that was still valid. V12 added a “withdrawal” category to extraction (the user says something already recorded is wrong or no longer needed, without providing something new). Replacement V6 identifies which item was withdrawn.
- Data: historical messages imported from D:\ctm, not used for blk1mem or the second round of blk3obj (the 200 items in the first round of blk3obj were not recorded, so there may be a small overlap; those two rounds evaluated V10 and V11, and V12 did not refer to them).
  From 1500 random items, flash screened out 22 withdrawal-category items, and another 100 items were selected. Two judges were unaware of the version; only agreed items were counted. One judge failed on 3 items, leaving 119.
- Results: V12 recorded no withdrawals (0 for both the 22 withdrawal-category items and the 97 others). It recorded fewer decisions in withdrawal-category messages instead (V6 recorded one each for “Then restore it after all” and “No need to calculate mean”; V12 recorded neither).
  New items that distorted the original meaning: 0 for both versions. Missed invalidations: 1 for both versions. V12 is not adopted.
- Reason: The extraction step cannot see already recorded items (since V5, replacement has been a separate step). It cannot distinguish “withdraw an already recorded item” from “a new negative requirement,” and records nothing when uncertain.
  For withdrawal-category messages in the historical data, the current approach (record the new negative requirement and have the replacement step invalidate the old one) did not produce distorted items. The pilot trial case was triggered by a `ctm.md` item written too early (eliminated by delaying the write).
- Error in the evaluation itself: When retrieving current items as of the message's time, items recorded by that message itself during import were also included (31 of 122 items). The replacement step compared the new item with its own old copy.
  Of the 24 instances marked invalid, 11 were items from the same turn. Therefore, this time, “marked invalid but actually still valid” (11/12 for both versions) cannot be taken as a conclusion about the replacement step.
  In future, when retrieving memory state from imported data, exclude items recorded in the current turn and later. Counts of incorrect replacement judgments must distinguish between “content carried by the new item” (a redundant replacement, with no loss) and “requirement lost.”

**Block 3: Replacement step retested using the corrected method (2026-11-24, `research/blk3rep`)**. Memory uses the state before the message (during import, items and messages have the same timestamp, so use the state 1 millisecond earlier; exclude items from the current turn and later),
with the current approach (memory V6＋replacement V5). 450 unused random messages from historical messages imported from D:\ctm; 16 messages with 30 replacements in total, plus another 80 without replacements to check for missed judgments; two judges, counting agreed items.
- 30 replacements: 14 losses (still-valid requirements invalidated), 11 correct, 0 with content carried by the new item, 5 disagreements; 18 missed judgments (overturned but still current).
- 11 of the 14 losses were the same situation as the one in the real pilot trial on 11-24: the executor misunderstood the user's rule, and the user restated it (“It's not just X that stays unchanged; all of Y stays unchanged”).
  Memory recorded the executor's misunderstanding as a rejected practice—which was correct—but the replacement step used this rejected practice to replace the rule the user had just restated.
  The cause was in the input to the replacement step: similar old items carried “(rejected),” but new items did not. The rejected practice read like a new requirement contradicting the old rule.
  The other 3 instances replaced an entire old item when only part of it had changed (round 7b tried retaining the rest, but that was not adopted).
- Missed judgments cost less (both items are handed to the executor, listed by time, with newer ones taking priority). A loss means a valid requirement will no longer reach the executor.
- Correction: New items also carry their type (rejected, questioned), consistent with old items (`remember.POLARITY`). This fills in information missing from the input; it does not add rules for error cases.
- Evaluation (`research/blk3pol`): Another 900 unused items were selected. The same extraction results were used for replacement without and with types. Only messages with rejected or questioned new items were affected (160 items). Of those, 13 had replacements under either approach. Both judges completed evaluations of 12 items; they saw the union of replacements from both approaches, without knowing which approach each came from. Agreed items: losses 10→3, correct 5→2, content carried 2→1, missed judgments 5→8 (when one approach got it right and the other did not, the latter was counted as a missed judgment), disagreements 3→2. Losses fell by 7, at the cost of 3 more missed judgments. When a judgment is missed, both items are handed to the executor, with newer ones taking priority, so the cost is much lower. Adopted.
  The sample is small (12 messages). The conclusion is consistent with the cause analysis and the real pilot trial case. The remaining 3 losses occurred under both approaches: one replaced an entire item when only part had changed, and two had questioned items replace rules.

**Block 4 reuse branch: What to forward when continuing with the original session (S3, 2026-11-20)**. Forwarding already included: the user's original words; newly established constraints, guidance, and decisions on the path that had not been forwarded; practices replaced or rejected during this period; notifications such as file changes;
queries answered in this session's branch; the most recent few turns elsewhere that this message, as selected by delivery, continues from (`uses_recent`); and content the user pointed to. Two omissions:
- `uses_recent` has no longer been output since delivery V9 (V6 was rejected because the context for new executors got worse; this reuse path was not evaluated at the time). Thus, what the user had just said in other work would no longer be forwarded to the session being resumed.
  `blk4fwd.py`: across four datasets, there were 92 messages delivered to existing sessions with other work intervening after the session's previous turn. The two judges agreed that 4 needed content from some of the intervening turns (only one judge thought so for 3 others).
  The historical data came from separate sessions (the user knew A could not see B and would repeat things), so this is a lower bound. The original text of the intervening turns had a median length of about 1950 Chinese characters. Changed so that code appends turns belonging to other work
  since this session last received a forward, within the most recent 6 turns (`context.FORWARD_BETWEEN`; consistent with the most recent 6 turns given to a new executor; the section heading states that the requirements in them belong only to their respective work).
- Concept S3 calls for forwarding “relevant query conclusions,” but previously only those answered in this session's branch were forwarded. Queries answered from memory, whose answers the user had seen, were not forwarded. Now all answered queries from this period attached to this work, its subwork, and its ancestors are forwarded.
- Test `test_reused_session_gets_turns_from_other_works`.

**Where the information missing from the current block 4 combination (b32gd) comes from (2026-11-20, `blk4.where`, cached separately by combination)**: Of about 48 items partially or not provided across four windows, the two people disagreed on the source for 21; 13 came from sibling work (all “partial”),
12 from other work, and 3 from parent or child work. Looking at some sibling cases: details for two items were in the middle of executor responses, while context only provides the last 1500 Chinese characters of a response (truncation; `NO_CLIP` was tested earlier, with a total of +9; not the main cause, so no change for now).
One item was a restriction the user had stated in a sibling that actually applied to the whole group. Memory recorded it at the sibling level (block 3's hierarchy), while the sibling section's heading said their constraints did not apply to the current task.
Also found: Markdown headings in quoted original executor responses (“## Needs your confirmation,” “## Rejected items”) became top-level sections in context, so executors could mistake them for CTM sections.
Fixed: heading markers at the start of lines in quoted original text (original exchange text, user's original words) are changed to full-width characters (`context._flat`; test `test_quoted_headings_do_not_open_sections`).

**Splitting steps mixed into one work item during maintenance**: Maintenance instructions V11 already have `split` (concept 5.6), but very few splits actually happened in replay. It mainly improves task tree readability; the executor's scene, later result delivery, and query scope are unaffected.
An independent evaluation would require new annotations for “which messages should be split out,” with high effort and little benefit, so it will not be done for now.

**Missed `uses` entries in block 2, by use (2026-11-20)**: Of 35 instances named by both people but not written by delivery in V15, 24 appeared only in the local tree (V15 specifies that only the IDs of candidates, research, and queries may be written), and 11 appeared among the candidates.
By the new work's position: 26 were its siblings—the new executor's context already includes sibling results (concept 5.2); 5 were in other branches of the same Goal, and 4 were in other branches or the new work had no parent node.
The real gap for block 4 is these 9 instances. “35 missed entries” exaggerates the impact. The rest is ambiguity in the structure itself, so the instructions will not be changed further.

**Performance: Time the user has to wait** (50 items from d1120, replay median 45 seconds): Before the executor starts work, there is a wait for pointing (flash, 2.9 seconds) and delivery (argon, 10.7 seconds, input 13,400 tokens).
When a question is asked, there is a wait for the answer from memory (argon, 19.7 seconds) and query routing (argon, 10.6 seconds). After the executor answers, there is a wait for the progress summary (argon, 15.1 seconds) before the relay. Memory writes and replacement comparisons happen after dispatch and do not affect waiting time.
- **Switch query routing to flash** (only a choice between “directly provide the answer from memory” and “dispatch read-only execution”): On 42 questions scored in agreement by two people using current answers, appropriate routing was argon 36, flash 37; median time 6.0→3.1 seconds.
  `query.handle(route_model=)`, the pipeline passes `light_model`.
- **Do not switch progress summaries to flash**: With flash writing V4, downstream-needed information present in summaries fell for r4 72%→38%, r1 62%→41%; sentence-by-sentence checks found at least one unsupported sentence in w1118 8→15, VigInt 4→13; verification status marked incorrectly in w1118 2→14.
  Median length was about 900→400 Chinese characters. It is a long-term record handed to later executors and the user, so argon is retained. The roughly 15-second wait after the executor answers is not eliminated for now.
- **Switch answers from memory to user questions to flash** (`pipeline.QUERY_LIGHT`): On the probe, the two people agreed that w1113 had argon 33/46 correct, flash 35/46; on unused d1120, argon 30/47, flash 27/47; totals 63 versus 62, with 5 versus 6 wrong,
  effectively tied within judge variation. On the same 5 questions, median time was 24.2→16.7 seconds, and it is cheaper. The path where CTM answers from memory on the user's behalf when an executor asks a question mid-work was not tested and still uses argon.
- **Wait after the executor answers**: The pilot marks the work on the tree as “tidying” while CTM prepares the relay (`Pilot.tidying`), rather than leaving it blank for more than ten seconds. This does not enter the conversation (only things requiring the user enter the conversation).
- Reasoning effort for all three argon calls is already low.
- Delivery input (earlyg median about 22,000 Chinese characters): candidates 44.5% (half of that is the two most recent results for each candidate), local tree 29.1% (each item has only a title, status, and parent node, with 17% overlap with candidates), recent conversation 12%, Goal 8.9%.
  **Give candidates only the most recent result** (`deliver.CAND_RESULTS=1`; for deciding a delivery destination, what matters is what this work most recently did; the second-to-last result offers limited help): on earlyg, delivery destinations and placement were level (wrong parent node 4→1),
  `uses` written correctly 57→54, missed 35→39 (rescoring variation about 6); test not used for the decision: delivered to the correct work 231→234/255, new work created when needed 36→33/46, level overall. Median delivery input 12,100→11,300 tokens.
- **Reuse connections for model calls**: Streaming reads closed the response as soon as `[DONE]` was read, leaving a short tail unread. The connection was discarded, and the next call repeated the TCP and TLS handshake (profiling: 4 calls and 4 handshakes for one message, about 2.1 seconds).
  Changed to read the stream tail fully before closing (`common/llm.py`, `CT_LLM_DRAIN`, on by default; if reading the tail fails, the answer is already complete and only that connection is lost). 8 consecutive calls: reconnections 6→0, no stalls. Saves about 2 seconds per message without affecting quality.
  The first test counted only “new connections” and missed “reconnections of discarded connections,” incorrectly concluding there was no benefit. This has been corrected.
- **Run stop classification and progress summary concurrently after the executor answers** (`pipeline.PARALLEL_STOP`): Stop classification needs only the contract and the end of the response. Both only call the model and do not read or write memory.
  Ran each twice on the same real response: serial 15.1, 17.8 seconds; parallel 12.3, 13.7 seconds (total time equals the progress summary alone), reducing the wait after each response by about 2 seconds.

## Method for Improvement (2026-11-19)

- Leave judgments that the model can make to the model. Code only stores, passes, and limits resources; derive the content of instructions from “who reads this output, what they use it for, and the cost of each kind of error,” not from observed errors, and do not include examples from those errors.
- Evaluate intermediate products by their actual downstream use: for progress summaries, check whether they contain the information later executors actually need (`summary_use`); for constraints, check delivery; for status, check the user's subsequent behavior.
- Keep data used to find causes of errors separate from test data; run the same configuration twice to check variation; compare versions using only judgments the two judges agree on; metrics with low judge agreement (such as “whether it fabricates,” often with more than ten disagreements out of 40 items) cannot distinguish versions that differ by a few items; choose based on principles in such cases.
- An improvement must meet both conditions: it gains on data not used to find causes of errors, and it can be justified in terms of use and cost.

## Tasks (in order)

### 1. Block 4 executor context: correct the measurement, remeasure the effect of filling in sibling context
- `fresh_pair`: For each new executor, opus lists information from previous conversations that the actual executor used (looking only at this message, the actual response, and content before the session), terra confirms item by item whether it was actually needed, and retain items both agree on;
  then each independently judges whether each item is complete, partial, or absent in each context group, counting only agreed items.
- Remeasure the old assembly method and filling in sibling context (reconstructed by point in time, paired): all new executors in w1113, plus new executors in each replay; target ≥40 points.
- Acceptance: the direction and magnitude of the difference between the two groups, and what is “absent” in each; the conclusion replaces the 11-18 “40%→52%” statement.
- Afterward (separately): take some points for an end-to-end evaluation—executors each write an execution plan with both contexts, and evaluate correctness against after-the-fact evidence.

### 2. Block 3 memory write: add consequence metrics and missing paths
- Consequence metrics: for each newly recorded constraint, which work receives it because of its location; two judges determine which work it should apply to (using the `cover` method for each item), yielding “should have reached but did not” and “reached but should not have.”
- Use opus and terra to re-annotate the four windows in block B (constraints, decisions, replacement pairs), and add a category for facts (environment, location, identifiers).
- Evaluate import (`bootstrap.SEG`) and memory during operation by the same standards: type (constraint, guidance, behavior guidance, global, one-time only) and location.
- Object constraints: the part that writes them to files can only be tested in a pilot trial or sandbox; mark it as unevaluated for now.

### 3. Block 6 work status and lifecycle: define boundaries, build a test set
- Boundary: one entry point is responsible for status judgment, dependencies and successors, folding upward, and rechecking after a decision is overturned (maintaining V11 status judgment and `lifecycle`); clearly specify inputs and outputs.
- Test set: take real scenarios from replays—successive work (whether the successor can be executed after the predecessor ends and receives the predecessor's results), replaced decisions (whether references to them are marked for rechecking), completion judgments (43 agreed annotations already exist; expand them).
- Either integrate the judgment of parent task completion into the runtime flow or revise it in the concept, and explain why.

### 4. Block 5 executor interaction: split up and evaluate separately
- 5a Continue using the original session or start a new one: use the user's subsequent words as after-the-fact evidence (a continuation sent to a new session, a new step inserted into an old session).
- 5b Execution control layer stop classification: E7 already exists (190 agreed annotations); keep it.
- 5c Progress summary: retest fabrication, omissions, and verification annotation on unused data with two judges.
- 5d Parts requiring real executors (constraint compliance, questions to CTM, formal completion checks, budget stops): design a plan for redoing historical tasks in a sandbox, specify the cost, then decide whether to do it.

## Progress (2026-11-19)

**Task 1 complete** (`auto_eval.py fresh_pair <w> <run>`): 35 points, 106 items of needed information agreed on by both judges. Before filling in sibling context, present／partial／absent 31%／48%／20%; after filling in, 43%／45%／12%;
“absent” for the user's work this week went from 32%→15% for r1 and 19%→16% for r4, with almost no change for aider. The conclusion replaces the original “40%→52%.” Most of what remains is “partial”: details are in long responses but not written in the progress summary—the direction for block 4's next step (connected to the 5c progress summary).

**Task 2 in progress**:
- Re-annotated four windows with opus and terra (`B2_GOLD=gold-ot python blockB2.py annotate|gold|repl_gold|score|prec`; precision was changed so that the two judge independently and only agreed items count, and the results directory switches with the label—
  previously the precision directory did not switch with the label, and an old cache was read; this has been fixed).
- Consequence metric `auto_eval.py reach_b2 <win> <cfg>`: for each constraint recorded given the input, compare the work both judges agree it should apply to with the work reachable from where it is attached.

| Four windows combined | V5 | V6 (current) |
|---|---|---|
| Constraint recall／decision recall | 50/52、52/56 | 50/52、53/56 |
| Precision valid／disagreement／wrong type／one-time only／wrong | 70%／12%／12%／6%／1% | 69%／13%／11%／5%／1% |
| Constraints that should have reached but did not (pairs) | 59（139） | 11（41） |
| Constraints that reached but should not have (pairs) | 8（13） | 21（62） |
| System replacements judged wrong by terra | 5/16 | 12/23（in the morning, both agreed on 4 correct and 4 wrong） |

  The two versions are the same in whether they record items and whether they record them correctly; the difference is in the consequences: V6 greatly reduces constraints that should have reached but did not, at the cost of attaching requirements for individual work too high, causing them to reach too much work. The next step for block 3 is to optimize the attachment level, using the metrics in this table.
- **V7 not adopted** (choose attachment level by consequences: provide the work below each node in the input, concept 3.4 “check using the consequences of constraints”; `remember.PROMPT_V7` retained). Development windows dev1+dev2, V6 and V7 each run twice:
  should have reached but did not V6 7 items (11 pairs), 7 (10); V7 17 (35), 16 (33). Reached but should not have V6 11 (29), 15 (22); V7 14 (21), 7 (12). After seeing the work below, it attached constraints lower, missing far more; the cost of missing a constraint (the executor violates the user's requirement) is greater than carrying an extra one.
- Measurement variation: two runs of the same version differ by 10–20% in the number of reached pairs; one judge (terra) judging replacement correctness produced very different results across two runs (dev2 V6 3 correct and 7 wrong versus 4 correct and 4 wrong)—replacement versions can only be compared using judgments both agree on.
- **Replacement comparison V3, set as default** (`remember.REPLACE = REPLACE_V3`). For replacements both judges agreed were wrong, the causes were replacing an entire old item when only part of it changed, treating an addition as a modification, and treating a one-time action (starting over) as an overturn.
  The cost of a missed judgment stated in V1 (“the executor will follow the outdated item”) did not match reality—context is listed chronologically and notes that newer items take priority—and it did not say that replacing an entire item would lose the parts that had not changed. V3 accurately states the costs of both kinds of error and first analyzes what things the old item says and which of them the new item changes.
  Offline paired comparison (`D:/tmp/repl_ab.py`: the same new items and the current items at the time from V6 run records, compared once with each of the two instructions, with both judges judging proposed replacements):

| | Proposed | Correct | Wrong | Disagreement |
|---|---|---|---|---|
| Development V1／V3 | 14／9 | 6／6 | 4／**0** | 4／3 |
| Test V1／V3 | 12／10 | 7／7 | 2／2 | 3／1 |

- **Replacement comparison changed to V5** (`remember.REPLACE`): V3 removes examples drawn from errors; the retained sentence follows from the meaning of replacement—replacement invalidates every sentence of the old item, so replace only when the old item as a whole no longer holds.
  V4, which states only consequences and costs without making this point explicit, was comparable to V1 on unused data. Data not used to find causes of errors (user's work this week r4, 189 messages, `D:/tmp/repl_ab2.py`):

| | Proposed | Correct | Wrong | Disagreement |
|---|---|---|---|---|
| V1 | 26 | 11 | 6–7 | 8–9 |
| V3 | 20 | 11 | 3–4 | 5–6 |
| V4 (consequences and costs only) | 26 | 11 | 5 | 10 |
| **V5** | 16 | 9 | **3** | 4 |

  (V1 and V3 were run twice; redoing the judgments once produced a difference of one item.)
- “Wrong type” in precision (other_type, about 13%) is actually the same content recorded as two types at once (such as both a constraint and a decision), not a type misclassification. V6 already has “record the same thing in only one place,” but it is only a rule.
  V8 states the reason (if recorded in two places, a later change replaces only one): the two-run average went from 13%→11%, with other metrics unchanged; the gain is within the range of variation, **not adopted**; replacement comparison finds current items by similarity, regardless of type, so both copies are compared, and the main risk is already covered by the mechanism.
- Not yet done: annotation of the fact category; evaluation of import (`SEG`) and memory during operation by the same standards.

**Entire flow (daily evaluation d1119-1421, user's 33 new messages on 11-19, all new defaults)**: 26 of 30 adjacent pairs in the same session were delivered to the same work; of the other 4 pairs, 2 were judged misdelivered, 1 correct, and 1 disputed;
there were no new executors; 5.06 calls per message, 20,800 input tokens, median 39 seconds (progress summary output became longer, and rate limits applied while running in parallel with other evaluations). Both misdeliveries were “Let's start implementing” and “Continue” after session switches, delivered to work in another session:
in concept 1.4, when the user moves to other work, they first select it on the tree (current task); the replay did not simulate this action. The replay was changed to set the current task to the work where that session was last active when switching sessions (`REPLAY_SELECT`, on by default);
it is only a hint for candidates and the “current task,” not an explicit designation by the user.
After simulated selection, one misdelivery remained: the current task for “Let's start implementing” was already the context-tree item, but delivery still followed the most recent turn of the conversation (a discussion of another item of work). The delivery instructions described current only as “the item the user last exchanged messages about,”
and did not say that it changes when the user selects other work on the tree, while the most recent turn may still belong to the previous work. **Delivery V13** adds this meaning (concept 1.2, 1.4; selection is the user's own action and has higher authority than an inference from the most recent turn), set as default:
block A earlyg differs from V11 by no more than one or two items in each category (this data has no cases of “selecting other work,” so it only shows no harm); for the user's 33 messages on 11-19, adjacent pairs in the same session delivered to the same work out of 30: original replay 26, simulated selection 27, simulated selection+V13 **29**, judged wrong 2→1→0.

**Task 3 in progress**:
- After-the-fact metric `auto_eval.py status_hind <w> <run>`: whether the user spoke again in the work after maintenance judged it ended. 4 out of 80 endings (mostly 0–0.1 hours after ending, with maintenance running just before the next message).
  The other side, “should have ended but did not,” is measured by `status_eval` (V11 36/43).
- In replays there are only 9 dependency references and 0 decisions that were replaced and referenced elsewhere: successor and rechecking scenarios must be annotated from conversations (two judges determine “which work's results the new work is built on”), or constructed using simulated users.
- Meaning of status (settled): in code, the executor's report is recorded only in the execution record, and task ending is judged only by CTM (in replays, “reported complete” is set entirely by maintenance); the issue is only naming. Concept 3.4 changed to “complete (based only on the executor's report), verified (complete and with evidence of verification)”; both are completions judged by CTM, differing in their basis; the interface's “reported complete” was renamed “complete (self-reported).” Status values are unchanged.
- Cause of status judgment errors (correction): the earlier statement that “label reasons and statuses were inconsistent” came from my analysis script matching the label values (ended_verified／ended_unverified／unfinished) incorrectly; the labels themselves had no problem. With the correct mapping, V11 was wrong on only 2 items among the labels both judges agreed on for the user's work this week r1: one where the executor reported completion and the user moved elsewhere and did not return, but it was not judged ended; one where the last record was still in progress and the user's follow-up had no response, but it was judged complete due to long inactivity. Status judgment is close to usable; the gap in block 6 is successors and rechecking, and replays have no such scenarios, so they must be constructed (simulated users).
- Successors receiving predecessor results (`auto_eval.py link_check <w> <run>`, using successors implicit in real data: information a new executor needs that comes from another work's response, with the source agreed on by both judges; check whether there is a reference,
  “follows,” dependency, or service relationship between the new work and the source work): user's work this week r4 (delivery creates `uses`) connected 26, not connected 8; r1 (delivery does not create references) connected 10, same parent 3, not connected 12. Most unconnected cases came from a message misdelivered at the start of the replay
  (the snapshot's current task did not match reality), and the source relationship for one research item that the checking script had not yet matched.
- On-demand judgment of parent task completion: across all replays (user's work this week r1, r4, aider), there were 0 cases where “all subtasks have ended, but the parent is still open,” so there is no occasion to use it now; do not integrate it for now (`lifecycle.parent_completion` retained), and integrate it into maintenance's status recheck and evaluate it when such cases appear in the data. The folded result text was changed to “complete (self-reported).”

**Task 4 in progress**:
- 5a Continue in the original session or start a new one (`auto_eval.py session_choice <w> <run>`, using whether the user stayed in the same session or started a new one in the user's original data as the retrospective basis): Of the user's 323 dispatches in r4 this week,
  all 49 cases where the user stayed in the original session but CTM started a new one had reasons—13 were new work (what is missing is measured by block 4), and 36 were read-only queries split off from this work's session (with history carried over); 0 cases started a new session for the same work.
  User started a new session but CTM reused one: 1–3 cases in the user's data, more in aider (the user often starts new sessions; agentic starts a new one through the framework for every message). No problems found.
- 5c Progress summaries (`auto_eval.py progress_eval <w> <run> [n] [version]`, blockF's judging instructions, opus and terra, counting only agreed items; the replay has no tool records, so modified files are used as execution traces):
  In 40 items from the user's new w1118 data, contained fabrication 3／27／10 (yes／no／disagreement), had omissions 25／6／9, verification labeled correctly 38/40; in 77 aider items, fabrication 8／53／16 (mostly because the judge treated aider's automatically applied SEARCH/REPLACE as not having modified files), omissions 42／22／13.
  What was omitted is what someone taking over needs: things left for the user to do and their deadlines, the reasons for decisions and key numbers, updated manuals, plans to execute after confirmation, pending conditional orders—the same problem as “partial” in block 4.
  V4 (explains the three uses of summaries and the costs of two kinds of errors, with analysis first) was compared with V3 in pairs on the same 93 responses (both versions were regenerated):

| | Has omissions (agreed) | Contains fabrication (agreed) | Verification labeled correctly (agreed) | Median length |
|---|---|---|---|---|
| V3 | 50 | 2 | 88 | 409 characters |
| V4 | **17** | 6 | 78 (the additional cases are disagreements: V4 uses separate labels such as “file modifications have traces; test pass is self-reported,” while the judging instructions only accept a choice between the two) | 1100 characters |

  The additional fabrications were minor overstatements. The categories V4 was to retain were derived from the key points omitted in this batch of data and could not be justified in principle, so it was rewritten according to the reader and use, and evaluated by downstream use (`auto_eval.py summary_use`:
  whether information from an executor's response that a later executor actually needs is present in that response's summary; 46 items in total from the user's r4 and r1 this week, both judges agreed):

| | Downstream: present | Fabrication (74 items from w1118+VigInt, both judges agreed) | Median length |
|---|---|---|---|
| V3 | about 40% | 2 | about 390 characters |
| V4 (lists categories to retain) | 68% | 5 | about 960 characters |
| V5 (reader and use; first analyze what is missing from the perspective of the person taking over) | 69% | 9 | about 1230 characters |
| V6 (V5 plus “every sentence must have a basis”) | 66% | 8 | about 1300 characters |
| **V7 (V5 plus general types of errors: speculating about causes, increasing the degree of certainty, changing the meaning of numbers, filling in objects that were not mentioned)** | 63% | 8 | about 1190 characters |

  “Whether it contains fabrication” was changed to item-by-item checking (`progress_eval ... J2`: first break the summary into separate statements, then look for a basis for each in the response and execution traces, following fact-checking methods such as FActScore): disagreements between the two judges did not decrease, but the versions could be distinguished—
  Of those both judges agreed had “at least one sentence without a basis” (74 items from w1118+VigInt), V3 had 7, **V4 12**, V5 18, V7 19; the proportion of sentences without a basis (for each of the two judges respectively) in the user's data was V3 2.3%／6.4%, V4 2.1%／3.4%, V7 2.0%／4.8%,
  and in aider's VigInt it was V3 2.3%／5.2%, V4 3.3%／4.2%, V7 5.4%／9.3%. The longer versions had more fabrication mainly because they wrote more than half as many additional statements; V5 and V7 were also more likely to make errors per sentence on the unused aider data.
  Principle: writing a summary is selecting and compressing from the response, not filling it in. V5 and V7 ask the model to “think about what is still missing from the perspective of the person taking over,” which amounts to inviting it to fill things in; V4's analysis asks “which things in the response must the person taking over know, and which are certain.”
  The categories V4 lists correspond to the progress content in concept 3.4 (what was done, what was changed, verification, pending items, failed approaches) plus “who is waiting for what.” My earlier judgment that it could not be justified in principle was wrong. **Change the default back to V4**.
  Impact on block 4 (`auto_eval.py fresh_prog <w> <run>`: replace the progress summaries in replay memory with V4 summaries regenerated from the same responses, rebuild context at the same moment, and judge the same set of needed information in pairs):

| User this week | Current (V3 summaries, budget 24,000) | V4 summaries, 24,000 | **V4 summaries, 32,000** |
|---|---|---|---|
| r4 41 items present／partial／absent | 30%／54%／16% (20.5k characters) | 37%／47%／16% (16.9k) | **47%**／37%／16% (24.3k) |
| r1 37 items | 33%／52%／15% (20.2k) | 25%／57%／18% (14.7k) | **37%**／47%／17% (20.8k) |

  V4's summaries are longer. With a budget of 24,000, the original text of sibling exchanges is cut first (much of the missing information is there), and the two effects cancel out; with the budget raised to 32,000, complete information rises from about 31%→44%, and the median context length is comparable to the current one.
  Degradation by value (`context.VALUE_DEGRADE`: when over budget, divide each exchange's vector similarity to the current message by its length, and degrade them one level starting with the lowest; do not degrade the most recent three turns of the current task):
  At the same 24,000-character budget, complete information rose from 37%→39% for r4 and 25%→28% for r1; fixed steps often cut more than necessary (median 16.9k versus 22.2k). The gain is within the range of variation, and it adds another vector call during assembly, so **do not adopt it for now**; the size of the budget has a greater effect than how cuts are made.
  **Change the budget to 32,000 characters** (`context.BUDGET`; the executor is a pi session with a very large window, and 32,000 characters is still a small context). The remaining approximately 16% that is “absent” is under other Goals and must be obtained through cross-task references.

**Causes of errors in block 4** (`auto_eval.py fresh_where <w> <run>`: identify which earlier message needed information that is only partially present or absent came from, with both judges agreeing, then examine the relationship between that message's work and the new work): Of approximately 45 items in the user's r1 and r4 this week,
19 came from executor responses in sibling work, 14 from executor responses in work under other Goals, 11 could not be determined, 0 from the same work, and 0 from the user's words. All the missing information consists of details in executor responses: these depend on progress summaries (V4 has been adopted) and the original text of sibling exchanges;
those under other Goals can only be obtained through cross-task references or by the executor asking.

## Out of scope for this plan
Blocks 7 and 8; continued optimization of delivery and tree organization; user pilot trial.
