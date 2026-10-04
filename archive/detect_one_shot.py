"""One-shot detector print for testing: compact, greppable JSON lines."""
import json
import sys

import get_desktop_state

state = get_desktop_state.get_desktop_state(sys.argv[1] if len(sys.argv) > 1 else None)
print(json.dumps(state, ensure_ascii=False))
