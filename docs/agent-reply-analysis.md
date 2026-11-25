# Agent Reply Analysis

> Purpose: To explain what executor agent replies contain and which content is actually used by the user and subsequent work. This provides a basis for
> result processing (5.2 item 6), output conventions, and document design in the [CTM concept model](ctm-concept-model.md). Data comes from the history within sessions; private data is in `research/agent-reply-analysis-01/`,
> and only summaries and anonymized relays are given here.

## 1. Method
- Data: Agent final replies from 15,031 user turns (excluding tool output), from 415 sessions. Median reply length was about 800 characters,
  and the 90th percentile was about 2,900 characters; 40% had headings or tables; the median number of tool calls was 3, and the 90th percentile was 19.
- Open coding: 80 replies (at most 3 per session). The model freely named information units and explained who would need them later; 15 categories and attribute dimensions were then derived.
- Calibration annotation: Another 400 replies (226 sessions, with no overlap with the open set) were split into 2,633 information units and annotated for type, position, degree of verification, execution stage,
  validity, timeliness, and retention period. The next 3 user messages were checked to determine whether each unit was referenced, adopted, corrected, or followed up on.
- Long-term needs: For each of 78 long-term state questions, it was determined whether the information in the reference answer came from user messages or agent replies, and, for information from replies, its category and position.

## 2. What Replies Contain
| Type | Units | Share of characters | Main position | Corrected later | Followed up on |
|---|---:|---:|---|---:|---:|
| Technical mechanisms and interface semantics | 448 | 21.6% | Middle 61% | 25 | 85 |
| Implementation, troubleshooting, and experiment plans | 396 | 18.4% | Middle, end | 40 | 57 |
| Configuration parameters, mappings, and calculation rules | 295 | 14.5% | Middle 77% | 23 | 48 |
| Diagnostic hypotheses and causal explanations | 278 | 9.5% | Middle | 24 | 64 |
| Change and operation records | 275 | 7.9% | Middle, end | 20 | 22 |
| Process narration | 210 | 8.2% | Beginning 80% | 3 | 0 |
| Verification results and coverage boundaries | 132 | 4.1% | Middle, end | 5 | 18 |
| Runtime and environment state snapshots | 108 | 2.9% | Middle | 5 | 12 |
| Pending questions, blockers, and handoff to-dos | 89 | 1.5% | End 75% | 6 | 12 |
| Corrections, withdrawals, and replacement relationships | 68 | 1.8% | Beginning, middle | 8 | 4 |
| Failure symptoms and impact | 63 | 1.6% | Middle | 2 | 8 |
| Location indexes and related samples | 60 | 2.0% | End | 2 | 4 |
| Constraints and acceptance contracts (agent restatements) | 59 | 0.8% | Middle | 2 | 3 |
| Measurement statistics and quantitative comparisons | 56 | 2.3% | Middle | 0 | 5 |
| Task goals and scope (agent restatements) | 41 | 1.3% | Beginning | 6 | 1 |
| Selection decisions and action authorization | 23 | 0.4% | End | 3 | 3 |

Attribute distribution (2,633 units):

- Verification: unverified 61%, locally supported 21%, supported by direct evidence 4%, counterevidence or conflict present 4%. The number of tool calls does not equal verification.
- Execution stage: only proposed 21%, reported as executed 21%, in progress 6%, awaiting approval 2%, not applicable for the rest.
- Validity: current 35%, conditionally valid 21%, valid only historically 19%, pending 14%, disputed 6%, replaced, rejected, or withdrawn 5%.
- Timeliness: changes with the code version 52%, fixed historical anchor 21%, invalidated by deployment or configuration changes 10%, future commitment 9%, minute-level snapshot 2%.
- Retention period: task period 38%, version period 31%, short-term troubleshooting 14%, no retention needed 9%, audit only 6%, long-term core 3%.

## 3. What Is Needed Later
The 78 long-term state questions had 313 information sources in total: 46% came from user messages (66 requirements, 46 corrections, 22 decisions), and 54% came from agent replies.
Of those from replies: 44 technical mechanisms, 34 change records, 32 constraint restatements, 12 plans, 11 corrections, 10 configuration rules, 8 verifications, 7 state snapshots, 5 decisions, and 5 locations.
Their positions in replies were dispersed (63 at the beginning, 56 in the middle, 51 at the end), and only 30% had been explicitly adopted by the user.

## 4. What the Next User Message and the Next Execution Turn Actually Use
Sections 2 and 3 only describe what replies contain, not who will use it. The user does not care about every detail in a reply, and the executor does not follow each one.
Therefore, for 372 sets of “reply → next user message → next agent reply,” the content in the previous reply that was actually used was judged based on what happened subsequently:

- **Understanding user intent**: 85% of the next user messages depended on the previous reply, but each depended on only about 1.2 pieces of content on average.
  Roles: objects referred to 142, content followed up on 124, statements rejected or corrected 71, results or states checked 42, plans approved or selected 37, objects for answers to agent questions 16.
  The types involved were mainly technical mechanisms 103, plans 60, changes 45, goal scope 41, diagnoses 33, and configuration 29.
- **Executing the next request** (the next agent turn’s work or planning for it): About 2.5 pieces of content were needed on average, about half of them essential.
  Roles: technical conclusions or mechanisms 276, file and code locations 128, plans or steps to be executed 111, completed results 110, configuration and parameters 105, verification status 102, pending questions 59.
- **Unused content**: In 56% of replies, most or almost all content was unused for either of these purposes; in another 24%, about half was unused.
  Typical examples were process updates, restatements of goals, unadopted speculation, line-number-level details, and conceptual explanations.

## 5. Conclusions
1. **Most of a reply is unused later**: In 56% of replies, most or almost all content is used neither to understand the user’s next message nor in the next execution turn.
   Process updates, restatements of goals, speculation that no one follows up on, line-number-level details, and conceptual explanations are the most common.
2. **The user cares about the one or two points they refer to**: 85% of next messages depend on the previous reply, but each depends on only about 1.2 points on average, mostly for reference, follow-up, rejection, checking, or approval.
3. **Continuing work requires a small number of key points**: About 2.5 on average, mainly technical conclusions, file and code locations, steps to be executed, completed results, configuration, verification status, and pending questions.
4. **The main objects of user correction** are the agent’s plans, statements about mechanisms, diagnoses, and configuration rules; **61% of statements have no visible evidence**, and many tool calls do not mean they have been verified.
5. **Knowledge of long-term value** (mechanisms, rules, design conclusions) is distributed in the middle of replies and is suited to being consolidated in documents that can evolve, rather than split into numerous entries or left in the conversation.

## 6. Handling in CTM
| Stage | Handling |
|---|---|
| Output convention (written in the execution contract) | Write long content into documents; replies to CTM contain only brief results: what was done, which documents and files were updated, verification status, unresolved issues, and matters requiring user decisions |
| Reply arrival | Save the original text and traces as execution evidence; CTM writes a brief summary into task progress; if the reply still contains lengthy content, save it as a document |
| Relay to the user | Relay only what the user needs to know or decide: completion, blockers, deviations from expectations, and pending items; number the items for reference; state which conclusions are supported by traces |
| User's response | Apply it to the item pointed to: approval becomes a decision, rejection becomes a rejected proposal and the new statement is recorded, and follow-up questions become pending items |
| Other details | Leave them in documents and execution evidence, to be retrieved when needed or read by the executor itself |
