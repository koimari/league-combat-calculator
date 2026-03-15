---
name: new-champion
description: Implement a new champion in the LoL calculator from a user-provided ability breakdown. Only invoke when the user explicitly types /new-champion.
user-invocable: true
disable-model-invocation: true
---

# New Champion Implementation

Load the `/add-champion` skill for full implementation guidance.

## User-Provided Ability Breakdown

The user has described the champion's abilities and any special considerations below. Parse this to determine whether a custom module is needed or the generic parser suffices.

$ARGUMENTS

## Instructions

1. **Inspect the champion's JSON data** using the script from the `/add-champion` skill
2. **Cross-reference** the user's notes above with the JSON structure
3. **Determine approach**: custom module vs generic parser
4. **Implement** following the `/add-champion` skill checklist:
   - Create module if needed (all values from JSON, no hardcoded numbers)
   - Register in `__init__.py` (alphabetical)
   - Add skill order override if not Q>W>E
   - Add frontend champion options and assumptions if needed
   - Create tests in `tests/test_<name>.py`
5. **Verify**: run `pytest` (all tests must pass)
