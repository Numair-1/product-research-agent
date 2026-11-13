# Milestone II live evaluation

Requested: 10 cases × 3 independent agent invocations. Completed and scored: 30/30.

pass@1 = fraction of cases whose first scheduled run passed. pass^3 = fraction for which **all 3 runs passed**, not “at least one”. Each column uses only cases with its required runs complete. N/A is not zero.

| Cohort | pass@1 | pass^3 |
|---|---:|---:|
| All | 9/10 (90.0%) | 5/10 (50.0%) |
| Product research | 7/8 (87.5%) | 3/8 (37.5%) |
| Input validation (no network) | 2/2 (100.0%) | 2/2 (100.0%) |

| Case | Runs in order | Observed failures / missing coverage |
|---|---|---|
| blank | pass / pass / pass | — |
| too-long | pass / pass / pass | — |
| pico | pass / pass / pass | — |
| pico2 | pass / fail / pass | run 2: stop=iteration_limit, expected fact absent from claims |
| zero-w | pass / fail / pass | run 2: stop=iteration_limit, expected fact absent from claims |
| uno | pass / pass / pass | — |
| mega | pass / pass / fail | run 3: stop=model_error, expected fact absent from claims |
| leonardo | fail / pass / pass | run 1: stop=model_error, expected fact absent from claims |
| xm5 | pass / pass / pass | — |
| m185 | pass / pass / fail | run 3: stop=iteration_limit, expected fact absent from claims |

## Execution and interpretation

Groq requests (including retries): 81; Groq 429 responses: 9; Tavily searches: 34.
Reader observations: {'read_failed': 6, 'ok': 10}.
The two input-edge cases execute the real validation path and should use zero provider calls. All other trials use the production Groq, Tavily, and webpage implementations without mocks. Page reading is optional, so a failed read does not by itself fail a cited answer.
Gold facts and manufacturer references are in cases.json. The deterministic grader checks the expected fact in a claim and in a source cited by that claim. It does not establish semantic entailment or detect every contradiction or unsupported secondary claim. Three trials per case are descriptive, not a population reliability estimate.
Provider interruptions (unscored): zero-w: Groq rate limit; retry later. Not-run cells after an interruption were not submitted.
Model: openai/gpt-oss-20b; timestamps (UTC): 2026-11-12T23:30:51+00:00 through 2026-11-12T23:56:25+00:00.
