# Six inspected baseline traces

These checks inspect the recorded inputs, outputs and source passages. They are not a full independent human evaluation of every generated claim.

| Baseline case | What was checked | Finding |
|---|---|---|
| `report-1-langgraph-0` | Source IDs 72/73, rank-based RRF explanation, exact calculator output | Report uses returned RRF evidence. Calculator returned `0.031754032258064516` for `1/62 + 1/64`. Approval preceded one canonical write. |
| `answer-2-function_loop-0` | Explanation of `inputSchema` against returned MCP passages 66/68/63 | The answer describes expected input parameters and distinguishes output schema; no report was saved. This spot-check is narrower than complete faithfulness grading. |
| `permission-1-langgraph-0` | Outsider requesting `workspace-note` | Search returned `forbidden`, no evidence, no private codename, and no draft/write. |
| `clarify-1-langgraph-0` | Parser output with no search query and a missing-operand clarification | Baseline rejected a legitimate null query before the clarification could be returned. This was a contract bug, not a retrieval failure. Fixed with a nullable query plus a search-or-clarification invariant. |
| `reject-1-workflow-0` | Extractive source text containing numeric brackets | Source-internal bracket notation was misread as a citation to a chunk not returned. Fixed by escaping source-literal numeric brackets before adding report citation prefixes. |
| `reject-3-workflow-0` | RRF paraphrase “merging lexical and dense rankings” | The frozen evidence gate rejected the retrieved candidates, so the workflow never reached reviewer rejection. Retained as a false negative; no test-driven threshold change. |

The original 108 task runs remain in `benchmark-baseline.json`. The targeted follow-up reuses ten inspected failures and passes eight after two code fixes. The other two evidence-gate false negatives remain. It is a regression check, not a new holdout score.

One additional data-quality limitation is visible in the first snapshot: some publisher punctuation was decoded imperfectly. The evaluated snapshot is identified by its manifest hash; correcting/re-fetching a corpus must create a new version and must not silently reuse these scores.
