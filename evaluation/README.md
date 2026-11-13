# Product Research Agent: live evaluation

The files in `results/` are the unchanged **pre-approval-gate baseline** for
application commit `7d291af`. Open `results/REPORT.md` to view it. New runs and
report regeneration default to `post-gate-results/`; the archive is protected.
New runs skip every page read unless you pass `--interactive` and type
`APPROVE` for the exact URL displayed. Use the same approval policy to resume.

Run from the root of the release repository with Python 3.11+ and the packages in
`requirements.txt`. The harness imports the production agent, Groq client, Tavily
search and page reader. It does not start a server, deploy a change, or use a
second model as a judge.

## Reproduce or resume

Set the usual environment variables or use an existing private local credential
file. On this computer, PowerShell commands from the release repository are:

```powershell
$python = '..\stock\product_research\.venv\Scripts\python.exe'
& $python -B evaluation/run.py --report-only
& $python -B evaluation/run.py --env-file '..\stock\product_research\.env'
```

The first command regenerates the report from saved results without making
provider calls. The second **resumes** missing trials; it skips scored passes
and failures. For a **new independent evaluation**, use a new output directory:

```powershell
& $python -B evaluation/run.py --k 3 --out evaluation/new-run --env-file '..\stock\product_research\.env'
```

On another machine use its Python interpreter. Omit `--env-file` if the credentials
are already in the environment. A hosted Streamlit secrets file is not needed.
Never put keys into the dataset or results. Use one runner per output directory.

After transient throttling, `evaluation/resume_slow.py` accepts the same flags,
waits 65 seconds before starting, and spaces fresh decisions at least 20 seconds
apart. It resumes the same ledger and grading protocol. A blocked decision can
still retry once after the provider's delay. For prolonged or daily limits, wait
for the quota reset instead of repeatedly starting the runner.

## Protocol

- `cases.json` fixes the input, oracle, and reference for each case. The model sees
  the product prompt, not the answer key. The eight research cases ask for specific
  measurements or identifiers. The two edge cases are whitespace and input beyond
  the 200-character limit; they exercise the actual validation path without an API
  call. They are not tests of provider authentication.
- Each product trial starts a new production research loop with empty evidence and
  history. Research cases run sequentially, once per round. There is no answer
  caching or retry of a completed, failed answer. Cached provider-side content and
  shared search results can correlate runs.
- A research pass needs a completed bounded trace, a successful search, validated
  source IDs, and a matching fact in both a claim and the evidence linked to it.
  Either a search excerpt or a successful webpage read can support the fact.
  The eight facts are narrow regression checks, not a comprehensive fact check.
  Matching is lexical; equivalent paraphrases may fail, and mentioning a token
  in a negated or misattributed sentence may pass. The reference URL establishes
  the expected value; it is not the only acceptable citation.
- **pass@1:** number of eligible cases whose first scheduled run passed divided by
  cases with a scored first run. **pass^k:** number of eligible cases that passed
  *every* one of k trials divided by cases with all k scored trials. For example,
  pass/fail/pass counts toward pass@1 but **not** pass^3. The report also splits
  research and validation cases and shows coverage to make denominators explicit.
- Calls are serial, with at least 2.2 seconds between Groq request starts. No SDK
  retries. A Groq 429 may retry just the interrupted decision once, after the
  provider delay (or 60 seconds without a numeric delay). Longer or repeated
  throttling checkpoints a blocked trial and stops the batch. Resume after quota
  resets. Blocked attempts and unsubmitted trials are not scored; ordinary model
  failures, evidence failures, and iteration-limit stops count against the agent.
- `results/runs.jsonl` records statuses, UTC times, model, source and request counts,
  read outcomes and deterministic failure reasons; it does not store answers,
  provider bodies, credentials, or search text. Code/dataset fingerprints prevent
  resuming a batch with different conditions. An interruption mid-trial may consume
  calls before the checkpoint; use Ctrl+C between trials if possible.
- `results/REPORT.md` is generated from that ledger. No unit-test fixture counts
  toward the evaluation. Run the independent grader checks with
  `python -m unittest discover -s evaluation -p test_grader.py`.
