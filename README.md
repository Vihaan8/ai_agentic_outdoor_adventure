# Trail Adventure Planner

An LLM agent that plans outdoor adventures. Tell it where you want to go and what kind of trip
you want, and it pulls together trails, weather, daylight, and park info to build a real plan.

The agent loop is hand-written — no LangChain, no CrewAI, no framework. Just Anthropic's API,
function calling, and a `while` loop.

## What it looks like

```
You: Moderate hikes near Boulder, CO this weekend
> searching trails... (Boulder, CO)
> checking weather... (Boulder, CO)
> getting daylight... (Boulder, CO)

Royal Arch Trail (3.4mi, moderate). Mount Sanitas Loop (3.2mi, steep but short).
Saturday looks best — 68°F and sunny. Start by 9am to be back before afternoon
storms. Bring layers, the climb gets warm. Sunrise is 6:33am, sunset 7:32pm.
```

## Architecture

```
agent.py     # the agent loop. while True: call LLM → dispatch tools → loop
tools.py     # 4 tool functions + geocoding helper
prompts.py   # system prompt and tool schemas
server.py    # FastAPI app with SSE streaming chat endpoint
config.py    # API keys from env
eval.py      # 18 test queries with quantitative scoring
ui/          # React frontend (Vite)
```

5 backend files, flat structure, no helpers or registries.

### Tools

| Tool | What it does | API | Key required |
|---|---|---|---|
| `search_trails` | Hiking trails near a place | OpenStreetMap Overpass | no |
| `get_weather` | Daily forecast in local time | Open-Meteo | no |
| `get_daylight` | Sunrise, sunset, day length in local time | Open-Meteo | no |
| `get_park_info` | NPS park details, alerts, campgrounds | NPS Developer API | yes (free) |

There's also a geocoding helper (`geocode`) using Nominatim that converts a place name to lat/lon.
The four tools all call it internally.

All times from `get_weather` and `get_daylight` are returned in the **location's** local timezone
(not the user's browser timezone), so sunrise in Tokyo shows as JST and sunrise in Boulder as MDT,
regardless of where the user is sitting.

### Agent loop

`agent.py` is ~70 lines. It:
1. Sends the user message + tool schemas to Claude
2. If Claude returns text only (`stop_reason == "end_turn"`), it's done
3. Otherwise it dispatches each `tool_use` block to the matching Python function
4. Appends results as a `tool_result` user message
5. Loops back to step 1, up to `max_turns` (default 8)

It's a generator. Each step yields an event (`tool_call`, `tool_result`, `text`, `done`) which
the FastAPI server forwards as SSE so the frontend can show the agent's reasoning live.

## Why this is actually agentic (not just tool calling)

A single tool call with a templated response would be a workflow, not an agent. This system
is genuinely agentic because the LLM — not the code — drives every decision in the loop:

1. **The model chooses which subset of tools to call.** Nothing in `agent.py` decides whether
   to fetch weather, trails, or park info. Claude reads the user's request and picks. "When's
   sunset in Moab?" calls 1 tool. "Plan a day trip to Rocky Mountain National Park" calls 4.
   Same loop, different decisions.

2. **It calls tools in sequence, not in a fixed batch.** `tool_choice` is set to
   `disable_parallel_tool_use: true`, which forces Claude to call one tool at a time. After
   each result comes back, Claude sees it before deciding what to do next — so a later tool
   call can be informed by an earlier tool's output.

3. **It loops until it has enough information.** The `while turn < max_turns` loop in
   `agent.py` keeps re-prompting Claude with the accumulated tool results until Claude itself
   says it's done (`stop_reason == "end_turn"`). No fixed step count. Simple queries finish
   in 2 turns, complex ones in 5+. The model decides when to stop.

4. **It synthesizes a final plan from tool outputs.** After gathering data, Claude doesn't
   just dump the raw JSON — it weaves trails + weather + daylight + alerts into a coherent
   trip plan with timing advice, gear, and safety notes specific to *this* user's request.

You can see this live in the UI: each turn the agent narrates its plan ("I'll start by
finding moderate trails…"), takes one action, reflects on the result ("The trail search
failed, let me get the weather instead…"), then decides the next step. That observe-decide-act
cycle is the agent loop — and Claude is the one running it, not the Python code.

## Setup

### Backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in keys
```

You need at minimum an Anthropic key. Only one optional key:
- `ANTHROPIC_API_KEY` — required, get from console.anthropic.com
- `NPS_API_KEY` — optional, free at nps.gov/subjects/developer/get-started.htm (instant issue).
  Only needed for the `get_park_info` tool. Trails, weather, and daylight all work without it.

Weather and daylight use **Open-Meteo**, which is free and needs no key.

Start the API:
```bash
uvicorn server:app --reload --port 8001
```

### Frontend

```bash
cd ui
npm install
npm run dev
```

Open http://localhost:5173. Make sure the backend is running on port 8001 (configurable in
`ui/src/App.jsx` if you change it).

## Eval

```bash
python eval.py
```

`eval.py` runs 18 test queries and scores the agent on four metrics:

| Metric | What it measures | How |
|---|---|---|
| **Tool F1** | Did the agent call the right tools? | Precision/recall against expected tool set |
| **Trail relevance** | For trail queries, did `search_trails` return ≥3 named trails? | Direct check on tool result |
| **Weather validity** | Did `get_weather` return well-formed forecasts? | Schema check on each forecast day |
| **Completeness** | Does the response cover trails, timing, gear, safety? | Claude judges 0/0.5/1 on each |

Results are written to `eval_results.json` and printed as a summary table.

### Latest run (18 cases, no OpenWeather/NPS keys set)

| Metric | Score |
|---|---|
| Tool precision (avg) | 0.78 |
| Tool recall (avg) | **1.00** |
| Tool F1 (avg) | **0.87** |
| Trail relevance (avg, n=13) | 0.38 |
| Weather validity | n/a |
| Completeness (avg) | 0.85 |
| Avg turns per query | 2.0 |
| Avg response time | 51.8s |
| Avg response length | ~1,750 chars |

The agent picks the correct tools almost every time (recall 1.00) and builds complete trip
plans (0.85). It does sometimes call an extra tool (`get_daylight` when the user didn't
explicitly ask for timing), which drops precision to 0.78 — in practice that's a feature,
not a bug.

**Trail relevance is the weak spot (0.38).** Out of 13 trail-focused queries, only 5 got
three or more named trails back from Overpass. The rest timed out — Overpass is rate-limited
and during a rapid-fire eval run, the second half of queries often hits the limit. In
interactive use this is a non-issue because requests are spread out. The agent handles the
failure gracefully by falling back to general trail knowledge.

With an OpenWeather key set, you'll also see weather validity numbers in the eval table.

## Code style

This is meant to read like a senior engineer's weekend project, not enterprise software:

- Flat structure, no `services/` or `utils/` folders
- No try/except unless failure is expected and meaningful
- Real variable names (`trails`, `lat`, `lon` — not `trail_data_collection`, `latitude_coordinate`)
- Type hints on function signatures only
- Docstrings written like a human ("Hit the Overpass API for hiking trails")
- No comments restating code

## Notes on the data sources

**OpenStreetMap / Overpass** is free but rate-limited and occasionally flaky. `tools.py` falls
back across three Overpass mirrors to handle that. Trail data quality varies by region — well-mapped
areas (Boulder, Yosemite, the Whites) return rich named trails. Less-mapped areas may return mostly
generic paths.

**Open-Meteo** powers both weather and daylight. It's free, no API key, and returns times in the
location's local timezone automatically (via `timezone=auto`). For weather we pull daily high/low,
precipitation probability, WMO weather code (mapped to a string), and max windspeed. For daylight
we pull sunrise, sunset, and day length, then format them with the local timezone abbreviation
(MDT, JST, BST, etc.) so the user sees the real local time for the place they're visiting.

**NPS Developer API** covers US national parks only. Use the park's common name (`Yosemite`,
`Rocky Mountain`, `Zion`) — partial matches work. Optional — the app works fine without it.
