# Connectors

Bridges between real AI tools and CoWork Index. A connector reads what an
AI tool records about a user's session, ships each prompt/response pair
to `POST /connectors/exchanges`, and the API turns it into an
`interaction_events` row (plus, optionally, an `interaction_contents`
row with the raw text).

## Claude Code (`connectors/claude_code`)

Claude Code keeps every session as a JSONL transcript under
`~/.claude/projects/<project>/<session>.jsonl` and can run *hooks* on
lifecycle events. The connector uses both:

| Piece | What it does |
|---|---|
| `transcript.py` | Parses a transcript into `Exchange` objects (prompt, response, tools used, token usage, timestamps, next prompt = feedback, interruptions, tool denials). Stdlib only. |
| `hook.py` | Registered as a Claude Code hook (`Stop` + `UserPromptSubmit`). On every turn it re-parses the session transcript and upserts the exchanges that changed. Never blocks Claude: all errors are swallowed and logged to `~/.cowork_index/hook.log`. |
| `backfill.py` | One-shot import of all historical transcripts (`--project` to filter, `--dry-run` to count). |
| `install_hook.py` | Adds/removes the hook entry in `~/.claude/settings.json` and stores the employee mapping in `~/.cowork_index/config.json`. |
| `client.py` | HTTP client + local change-detection state so unchanged turns are not re-sent. |

### Setup

```bash
# 1. API must be running (docker compose up -d)
# 2. register the hook and map this machine's user to an employee
python -m connectors.claude_code.install_hook --employee "Burak Önce" --team "Veri & Analitik"
# 3. import history (optional but recommended for a full dashboard)
python -m connectors.claude_code.backfill --employee "Burak Önce"
```

Restart Claude Code after installing the hook. From then on every
exchange with Claude appears in the dashboard's **Live: Agents** tab within
seconds, tagged `source=claude_code`.

### Configuration (API side, `.env` / docker-compose)

| Variable | Default | Meaning |
|---|---|---|
| `CAPTURE_CONTENT` | `true` | Store raw prompt/response text in `interaction_contents`. Set `false` for the content-free mode. |
| `SIGNAL_CLASSIFIER` | `auto` | `auto` = Claude when an API key exists, else heuristics; `claude`; `heuristic`. |
| `ANTHROPIC_API_KEY` | – | Enables Claude-based classification of judgment signals. |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | Model used for classification. |

### What is extracted from one exchange

Deterministic (always local): input/output/cache tokens and USD cost, turn
index in session, agent model and effort/thinking level (e.g. "claude-sonnet-5", "high"), project folder, git branch, timestamps, sentence
count, average sentence length, exclamation density, politeness markers,
imperative (directive) ratio, tool calls (name + target), tool errors and
permission denials, interruptions.

Judgment (Claude when available, heuristics otherwise): `action_type`
(accepted / edited / rejected — inferred from the user's *next* prompt and
tool denials), `had_disagreement`, `persuasion_direction`,
`outcome_status` (production / test_only / abandoned), `critical_check_flag`,
`task_category`. Both the heuristic and the Claude verdict are stored in
`signals_json` so the dashboard can show how each field was decided.

Hard evidence overrides the model: an interrupted turn or a denied tool call
is always `rejected` / `abandoned`.

## GitHub Copilot Chat (`connectors/copilot_chat`)

**Status: best-effort, unverified against a real conversation.** VS Code
stores Copilot Chat sessions as JSON under
`<VS Code user dir>/workspaceStorage/<hash>/chatSessions/*.jsonl` (one file
per session, despite the extension). This is **not a documented/stable
API** -- it's VS Code's own internal storage and can change between
releases. There is also no hook mechanism for Copilot Chat (unlike Claude
Code), so "live" capture works by polling those files for changes instead
of reacting to an event.

| Piece | What it does |
|---|---|
| `session_store.py` | Parses one session file into `Exchange` objects. Deliberately defensive: tries several plausible shapes for the message/response fields and skips a turn it can't recognize rather than raising. |
| `watcher.py` | Polls `chatSessions/*.jsonl` every N seconds (mtime-based) and syncs changed sessions. Run it in a terminal you leave open, or as a startup task. |
| `backfill.py` | One-shot import of all current sessions (`--debug` lists files that parsed as empty/unrecognized -- useful for checking the format assumptions against real data). |
| `client.py` | Same HTTP + change-detection pattern as the Claude Code connector, under its own state files (`~/.cowork_index/copilot_chat_*`). |

### Setup

```bash
# 1. API must be running (docker compose up -d)
# 2. one-shot import of whatever Copilot Chat sessions already exist
python -m connectors.copilot_chat.backfill --employee "Burak Önce" --team "Veri & Analitik"
# 3. for live capture, leave this running in a terminal
python -m connectors.copilot_chat.watcher --employee "Burak Önce"
```

### Known limitations

- **No token/cost data.** VS Code's local session store does not appear to
  record token usage the way Claude Code's transcript does, so
  `input_tokens`/`output_tokens` are `0` for Copilot-sourced events until a
  usage field is found in real data. Cost will show as $0 for this source.
- **No hook, so not truly real-time.** The watcher's polling interval
  (default 15s) is the capture latency, not instant like Claude Code's hook.
- **Schema unverified.** This machine has never had a real Copilot Chat
  conversation to test against (sessions were empty at implementation
  time). After your first real conversation, run
  `python -m connectors.copilot_chat.backfill --dry-run --debug` and check
  the exchange count/content look right; the field-extraction logic in
  `session_store.py` is the place to adjust if not.

