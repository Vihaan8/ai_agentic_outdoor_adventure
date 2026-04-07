"""Quantitative eval for the Trail Adventure Planner agent.

Runs N test queries and scores the agent on:
  - tool call accuracy (precision/recall against expected tools)
  - trail relevance (did trail search return real trails for trail queries?)
  - weather data validity (did get_weather return well-formed forecasts?)
  - completeness (LLM judge: does the plan cover trails, timing, gear, safety?)

Usage: python eval.py
"""
import json
import time
import anthropic
from agent import run_agent_sync
from config import ANTHROPIC_API_KEY, MODEL

judge = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


TEST_CASES = [
    {
        "id": 1,
        "query": "Moderate hikes near Boulder, CO this weekend",
        "expected_tools": {"search_trails", "get_weather", "get_daylight"},
        "is_trail_query": True,
        "is_park_query": False,
    },
    {
        "id": 2,
        "query": "Easy trails under 5 miles near Asheville, NC",
        "expected_tools": {"search_trails", "get_weather"},
        "is_trail_query": True,
        "is_park_query": False,
    },
    {
        "id": 3,
        "query": "Weekend camping trip planning in Yosemite National Park",
        "expected_tools": {"get_park_info", "get_weather"},
        "is_trail_query": False,
        "is_park_query": True,
    },
    {
        "id": 4,
        "query": "Sunrise hike ideas near Sedona, AZ with timing advice",
        "expected_tools": {"search_trails", "get_daylight"},
        "is_trail_query": True,
        "is_park_query": False,
    },
    {
        "id": 5,
        "query": "Challenging day hikes near Seattle, WA this weekend",
        "expected_tools": {"search_trails", "get_weather"},
        "is_trail_query": True,
        "is_park_query": False,
    },
    {
        "id": 6,
        "query": "Plan a day trip to Rocky Mountain National Park",
        "expected_tools": {"get_park_info", "search_trails", "get_weather"},
        "is_trail_query": True,
        "is_park_query": True,
    },
    {
        "id": 7,
        "query": "Easy family-friendly hikes near Portland, OR",
        "expected_tools": {"search_trails", "get_weather"},
        "is_trail_query": True,
        "is_park_query": False,
    },
    {
        "id": 8,
        "query": "When's sunset in Moab, UT on 2026-04-15?",
        "expected_tools": {"get_daylight"},
        "is_trail_query": False,
        "is_park_query": False,
    },
    {
        "id": 9,
        "query": "Good hiking trails around Zion National Park",
        "expected_tools": {"get_park_info", "search_trails"},
        "is_trail_query": True,
        "is_park_query": True,
    },
    {
        "id": 10,
        "query": "What's the weather like for hiking in Flagstaff, AZ this week?",
        "expected_tools": {"get_weather"},
        "is_trail_query": False,
        "is_park_query": False,
    },
    {
        "id": 11,
        "query": "Long day hike recommendations near Bend, OR with timing",
        "expected_tools": {"search_trails", "get_weather", "get_daylight"},
        "is_trail_query": True,
        "is_park_query": False,
    },
    {
        "id": 12,
        "query": "Current alerts and closures for Glacier National Park",
        "expected_tools": {"get_park_info"},
        "is_trail_query": False,
        "is_park_query": True,
    },
    {
        "id": 13,
        "query": "Beginner hikes near Burlington, VT with forecast",
        "expected_tools": {"search_trails", "get_weather"},
        "is_trail_query": True,
        "is_park_query": False,
    },
    {
        "id": 14,
        "query": "Photography-friendly trails near Jackson, WY golden hour",
        "expected_tools": {"search_trails", "get_daylight"},
        "is_trail_query": True,
        "is_park_query": False,
    },
    {
        "id": 15,
        "query": "Overnight backpacking in Grand Canyon National Park",
        "expected_tools": {"get_park_info", "get_weather"},
        "is_trail_query": False,
        "is_park_query": True,
    },
    {
        "id": 16,
        "query": "Quick 2-hour hike near Salt Lake City tomorrow morning",
        "expected_tools": {"search_trails", "get_weather", "get_daylight"},
        "is_trail_query": True,
        "is_park_query": False,
    },
    {
        "id": 17,
        "query": "Fall foliage hikes in the White Mountains, NH",
        "expected_tools": {"search_trails", "get_weather"},
        "is_trail_query": True,
        "is_park_query": False,
    },
    {
        "id": 18,
        "query": "Dog-friendly trails near Santa Fe, NM with current conditions",
        "expected_tools": {"search_trails", "get_weather"},
        "is_trail_query": True,
        "is_park_query": False,
    },
]


def score_tool_calls(expected, actual):
    """Precision/recall/F1 on tool call sets."""
    if not expected:
        return 1.0, 1.0, 1.0
    actual = set(actual)
    tp = len(expected & actual)
    precision = tp / len(actual) if actual else 0
    recall = tp / len(expected) if expected else 1
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
    return precision, recall, f1


def score_trails(tool_calls_with_results, is_trail_query):
    """For trail queries: did we actually get named trails back?"""
    if not is_trail_query:
        return None
    for entry in tool_calls_with_results:
        if entry["name"] == "search_trails":
            r = entry.get("result", {})
            if "error" in r:
                return 0.0
            return 1.0 if r.get("count", 0) >= 3 else 0.5
    return 0.0


def score_weather(tool_calls_with_results):
    """For weather queries: did get_weather return a valid forecast?"""
    for entry in tool_calls_with_results:
        if entry["name"] == "get_weather":
            r = entry.get("result", {})
            if "error" in r:
                return None
            forecast = r.get("forecast", [])
            if not forecast:
                return 0.0
            valid = sum(
                1
                for d in forecast
                if "high_f" in d and "low_f" in d and "conditions" in d
            )
            return valid / len(forecast)
    return None


def score_completeness(query, response_text):
    """LLM judge for how complete the trip plan is."""
    if not response_text.strip():
        return 0.0
    prompt = f"""You are evaluating whether a trip plan response is complete and useful.

USER QUERY: {query}

AGENT RESPONSE:
{response_text}

Rate the response on each criterion. Score 1 if present and specific, 0.5 if vague, 0 if missing:

1. SPECIFIC_TRAILS_OR_ACTIVITIES: Does it name specific trails, spots, or activities?
2. TIMING: Does it give timing advice (when to start, daylight, etc.)?
3. GEAR: Does it mention what to bring or wear?
4. SAFETY: Does it mention any safety consideration (weather, difficulty, alerts)?

Reply with ONLY a JSON object like: {{"trails": 1, "timing": 0.5, "gear": 1, "safety": 0}}"""

    resp = judge.messages.create(
        model=MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    text = next(b.text for b in resp.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.split("```")[1].replace("json", "", 1).strip()
    scores = json.loads(text)
    return sum(scores.values()) / 4


def run_eval():
    results = []
    print(f"\n{'='*80}")
    print(f"  TRAIL ADVENTURE PLANNER — EVAL ({len(TEST_CASES)} test cases)")
    print(f"{'='*80}\n")

    for i, case in enumerate(TEST_CASES, 1):
        print(f"[{i}/{len(TEST_CASES)}] {case['query'][:60]}")
        t0 = time.time()
        try:
            out = run_agent_sync(case["query"], max_turns=6)
            elapsed = time.time() - t0
            called = [tc["name"] for tc in out["tool_calls"]]
            calls_with_results = [
                {"name": e["name"], "result": e["result"]}
                for e in out["events"]
                if e["type"] == "tool_result"
            ]

            precision, recall, f1 = score_tool_calls(case["expected_tools"], called)
            trail_score = score_trails(calls_with_results, case["is_trail_query"])
            weather_score = score_weather(calls_with_results)
            completeness = score_completeness(case["query"], out["final_text"])

            result = {
                "id": case["id"],
                "query": case["query"],
                "expected_tools": sorted(case["expected_tools"]),
                "called_tools": called,
                "tool_precision": round(precision, 2),
                "tool_recall": round(recall, 2),
                "tool_f1": round(f1, 2),
                "trail_relevance": trail_score,
                "weather_validity": weather_score,
                "completeness": round(completeness, 2),
                "turns": out["turns"],
                "elapsed_s": round(elapsed, 1),
                "response_len": len(out["final_text"]),
            }
            results.append(result)
            print(
                f"   f1={f1:.2f} trails={trail_score} weather={weather_score} "
                f"complete={completeness:.2f} ({elapsed:.1f}s)"
            )
        except Exception as e:
            print(f"   ERROR: {e}")
            results.append({"id": case["id"], "query": case["query"], "error": str(e)})

    print(f"\n{'='*80}")
    print("  SUMMARY")
    print(f"{'='*80}")

    valid = [r for r in results if "error" not in r]
    if not valid:
        print("No successful runs.")
        return

    def avg(key, filter_none=False):
        vals = [r[key] for r in valid if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else 0

    print(f"  Cases run:             {len(valid)}/{len(results)}")
    print(f"  Tool precision (avg):  {avg('tool_precision'):.2f}")
    print(f"  Tool recall (avg):     {avg('tool_recall'):.2f}")
    print(f"  Tool F1 (avg):         {avg('tool_f1'):.2f}")

    trail_scores = [r["trail_relevance"] for r in valid if r["trail_relevance"] is not None]
    if trail_scores:
        print(f"  Trail relevance (avg): {sum(trail_scores)/len(trail_scores):.2f}  "
              f"(n={len(trail_scores)})")

    weather_scores = [r["weather_validity"] for r in valid if r["weather_validity"] is not None]
    if weather_scores:
        print(f"  Weather validity (avg):{sum(weather_scores)/len(weather_scores):.2f}  "
              f"(n={len(weather_scores)})")
    else:
        print(f"  Weather validity:      n/a (no OPENWEATHER_API_KEY)")

    print(f"  Completeness (avg):    {avg('completeness'):.2f}")
    print(f"  Avg turns:             {avg('turns'):.1f}")
    print(f"  Avg response time:     {avg('elapsed_s'):.1f}s")
    print(f"  Avg response length:   {int(avg('response_len'))} chars")
    print()

    print(f"  {'ID':<3} {'F1':<5} {'Trails':<7} {'Weather':<8} {'Complete':<9} Query")
    print(f"  {'-'*3} {'-'*5} {'-'*7} {'-'*8} {'-'*9} {'-'*50}")
    for r in valid:
        tr = f"{r['trail_relevance']:.2f}" if r["trail_relevance"] is not None else "  - "
        wx = f"{r['weather_validity']:.2f}" if r["weather_validity"] is not None else "  - "
        print(
            f"  {r['id']:<3} {r['tool_f1']:<5.2f} {tr:<7} {wx:<8} "
            f"{r['completeness']:<9.2f} {r['query'][:50]}"
        )

    with open("eval_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Full results written to eval_results.json\n")


if __name__ == "__main__":
    run_eval()
