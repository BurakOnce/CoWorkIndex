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
exchange with Claude appears in the dashboard's **Live: Claude** tab within
seconds.

### Configuration (API side, `.env` / docker-compose)

| Variable | Default | Meaning |
|---|---|---|
| `CAPTURE_CONTENT` | `true` | Store raw prompt/response text in `interaction_contents`. Set `false` for the content-free mode. |
| `SIGNAL_CLASSIFIER` | `auto` | `auto` = Claude when an API key exists, else heuristics; `claude`; `heuristic`. |
| `ANTHROPIC_API_KEY` | – | Enables Claude-based classification of judgment signals. |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | Model used for classification. |

### What is extracted from one exchange

Deterministic (always local): input/output/cache tokens and USD cost, turn
index in session, model, project folder, git branch, timestamps, sentence
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
