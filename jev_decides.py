"""Ask Jev (TypeSafe's decision model on OpenRouter) a yes/no question."""

import get_desktop_state
import json
import sys
import urllib.request

# OpenRouter API key (hard-coded for now)
API_KEY = "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"

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"
user_goal = input("What is your goal: ")
yes_threshold = 50.0


def decide(api_key: str, state: str, question: str, true_when: str,
           false_when: str, yes_threshold: float = 50.0) -> dict:
    """Ask Jev a yes/no (noul) question and return the decision.

    yes_threshold is the percent above which the answer counts as YES.
    """
    payload = {
        "model": MODEL,
        "state": state,
        "questions": {
            "decision": {
                "type": "noul",
                "instructions": question,
                "criteria": {
                    "true": true_when,
                    "false": false_when,
                },
            }
        },
    }

    req = urllib.request.Request(
        DECISIONS_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"API error {e.code}: {e.read().decode()}")

    yes_prob = data["answers"]["decision"]["noul"] * 100.0

    return {
        "yes_percent": round(yes_prob, 1),
        "no_percent": round(100.0 - yes_prob, 1),
        "answer": "YES" if yes_prob >= yes_threshold else "NO",
    }


if __name__ == "__main__":
    # Detect what the user is doing right now (see get_desktop_state.py).
    # Single-shot, no timers or polling yet — one run, one decision.
    state = get_desktop_state.get_desktop_state(user_goal=user_goal)
    get_desktop_state._print_state(state)

    result = decide(
        api_key=API_KEY,
        state=json.dumps(state),
        question="The user has set a goal for themselves to work on, and your job is to determine if what the user is currently doing is a distraction from that goal. Is what the user is currently doing a distraction from that goal? This is the goal that the user has set: \"" + user_goal + "\"",
        true_when="The user is engaging in an activity that is not aligned with their stated goal.",
        false_when="The user is engaging in an activity that is aligned with their stated goal.",
    )

    print(f"YES: {result['yes_percent']}%")
    print(f"NO:  {result['no_percent']}%")
    print(f"Decision (threshold {yes_threshold}%): {result['answer']}")
