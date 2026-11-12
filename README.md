# Multi-Agent Product Review and Comparison System

University Agentic AI project — Milestone II implements **only the Product Research Agent**.
No comparison, review-analysis, recommendation, or coordinator agents are implemented.

## Files and credentials

| File | Purpose |
| --- | --- |
| `app.py` | Streamlit input, research report, evidence, and JSON trace download |
| `agent.py` | Four-decision loop, validation, trace, and stop conditions |
| `services.py` | Groq tool selection and real Tavily HTTP search |
| `webpage.py` | Public-source webpage reader and readable text extraction |
| `test_webpage.py` | Reader, security, and agent recovery tests |
| `config.py` | Environment, `.env`, and Streamlit secrets loading |
| `test_agent.py` | Offline unit and Streamlit interface tests |
| `requirements.txt` | Python dependencies |
| `.env.example` | Empty credential template |

Required credentials:

- `GROQ_API_KEY`: create a key in your [Groq console](https://console.groq.com/keys). Your account needs model access and API quota.
- `TAVILY_API_KEY`: get a search API key from [Tavily](https://app.tavily.com/).
- Optional `GROQ_MODEL`: defaults to `openai/gpt-oss-20b`. Use a model available to your API account that supports tool calling on the free plan. The default is hosted by Groq; no OpenAI key is needed.

No paid API is required: use the Groq Free plan and Tavily free monthly credits.
Free limits apply; if exhausted, wait for reset rather than enabling a paid plan.
Keys are never included in source files or execution traces.
`.env` and `.streamlit/secrets.toml` are ignored by Git. Do not commit credentials.

## Windows PowerShell setup

Use Python 3.11 or newer. From this computer:

```powershell
# Open PowerShell in the cloned repository folder.
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Fill in the two empty key values in `.env`, save, and close Notepad. Do not repeat
the copy command over an existing configured `.env`.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open the displayed local address (normally http://localhost:8501). Enter a product
and click **Research Product**. Stop the server with Ctrl+C. Explicit interpreter
paths avoid PowerShell activation/execution-policy issues. If `python` is not
recognized, use `py` for the initial virtual environment command.

Alternatively set the keys as environment variables, or create `.streamlit/secrets.toml`:

```toml
GROQ_API_KEY = "your-key-here"
TAVILY_API_KEY = "your-key-here"
GROQ_MODEL = "openai/gpt-oss-20b"
```

Existing environment variables take precedence over `.env`, then Streamlit secrets.

## Paste your Groq key and restart the existing app

Open `the project folder's .env` in Notepad.
Paste the key after `GROQ_API_KEY=` (not into `.env.example` or Python source).
Keep your Tavily key after `TAVILY_API_KEY=` and leave
`GROQ_MODEL=openai/gpt-oss-20b`. Old `OPENAI_API_KEY` and `OPENAI_MODEL` entries
are unused and can be removed. Do not share the `.env` file.

After saving, run these PowerShell commands to restart the app on port 8501
in the background. Port 8501 is the port reserved for this application:

```powershell
# Open PowerShell in the cloned repository folder.
Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object { Stop-Process -Id $_ }
Start-Process -FilePath "$PWD\.venv\Scripts\python.exe" -ArgumentList '-m','streamlit','run','app.py','--server.port','8501','--server.address','127.0.0.1','--server.headless','true','--browser.gatherUsageStats','false' -WorkingDirectory $PWD -WindowStyle Hidden
```

Wait a few seconds and open http://localhost:8501. A full restart reloads `.env`
values; simply refreshing the browser may retain old environment values.
Groq free-plan requests may hit a rate limit; wait for the quota window to reset.

## How the agent works

The agent can search Tavily, read an exact URL from the current run, and finish a
report using the original source IDs. Four decisions total allow search → read →
finish, with one extra decision for a retry or another source. The agent can also
finish earlier using snippets. Failed reads are observations; the fourth decision
is the last, even if the agent has not produced a valid report.

The reader accepts HTTP/HTTPS on their default ports, validates DNS addresses and
connects directly to a checked public address. HTTPS still verifies the original
hostname. Requests do not use proxies, credentials, cookies, or automatic redirects.
All redirects are rejected; choose a direct search result instead. HTML and plain
text are accepted, with no JavaScript execution or compressed downloads. Limits:
512 KiB per response, 6,000 readable characters, 5-second network inactivity timeout,
and a 12-second overall network deadline. An inaccessible page can still have a
usable Tavily snippet. The trace distinguishes these two kinds of evidence.

Other stop reasons are `insufficient_evidence`, `model_error`, and `invalid_input`.
Search failures, empty results, invalid actions, and invalid citations are observations
that the model can respond to within the remaining budget. API retries are disabled
for the LLM; HTTP requests have timeouts.

The JSON download contains the product, UTC start time, iteration count, final answer,
source URLs and excerpts, stopping reason, and each decision summary, tool call and
tool observation. Decision summaries describe selected actions; private model reasoning
is never requested, displayed, or stored. The report persists across Streamlit reruns.

## Evidence and limitations

Production code has no sample-results mode or hardcoded product facts. Search snippets
are untrusted evidence, and the model is told to ignore instructions within them.
Every factual claim must cite IDs returned by search, with clickable URLs shown in the
interface and included in the download. Citation validation checks source membership,
not semantic truth: verify important statements against the source. Page excerpts and snippets may be incomplete, and current prices or variant differences may be
unresolved. Unsupported sections remain empty rather than being guessed.

## Testing and live verification

Run the offline suite with the unittest command above. It covers the decision cap,
source IDs, search and read failures, unsafe addresses, redirects, response limits,
text extraction, evidence in the trace, and Streamlit form and download behavior.
The suite uses simulated HTTP responses and does not need API keys.

To verify live integration after supplying credentials:

1. Run Streamlit and research a specific model such as `Sony WH-1000XM5`.
2. Check the trace for a real `web_search` call and returned URLs/excerpts.
3. If the agent chooses `read_webpage`, inspect its text (or read error) and source ID. Check that report citations correspond to retrieved sources and support the claims.
4. Download the JSON and check the final answer and stopping reason.

Missing keys show a setup error before the agent starts. If searches fail, check the
Tavily key, quota, and network. If the LLM fails, check Groq credentials, quota, and
model access. Empty results may require a more specific model name. These situations
never trigger fabricated research.

API references: [Groq tool calling](https://console.groq.com/docs/tool-use/overview),
[Groq free-plan limits](https://console.groq.com/docs/rate-limits),
[Tavily free credits](https://docs.tavily.com/documentation/api-credits),
[Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search),
[Streamlit AppTest](https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest).


## Streamlit Community Cloud

Select this repository, branch main, and main file path app.py. The adjacent
requirements.txt lists the dependencies. Select Python 3.11 or newer.
In Advanced settings > Secrets, set GROQ_API_KEY and TAVILY_API_KEY as
top-level TOML strings. Do not upload a local .env or secrets.toml file.