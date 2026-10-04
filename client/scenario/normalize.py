"""Coerce a raw scenario dict into something the executor can run."""
from schema import (
    BODIES, DEFAULTS, FACES, LOOKS, TOIO_COLORS, TOIO_GROUPS, TOIO_MOVES, TOIO_SOUNDS,
)

_ALLOWED = {
    "face": FACES,
    "look": LOOKS,
    "body": BODIES,
    "toio_move": TOIO_MOVES,
    "toio_group": TOIO_GROUPS,
    "toio_color": TOIO_COLORS,
    "toio_sound": TOIO_SOUNDS,
}


class ScenarioError(ValueError):
    """The scenario has no runnable step left after cleanup."""


def _enum(value, key):
    if isinstance(value, str) and value.strip().lower() in _ALLOWED[key]:
        return value.strip().lower()
    return DEFAULTS[key]


def _pause(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    return max(0, min(5, number))


def _say(value):
    text = "" if value is None else str(value)
    return " ".join(text.split())[:60]


def _empty(step):
    return (
        step["say"] == ""
        and step["face"] == "neutral"
        and step["look"] == "center"
        and step["body"] == "none"
        and step["toio_move"] == "none"
        and step["toio_color"] == "none"
        and step["toio_sound"] == "none"
    )


def normalize(raw):
    """Return a clean scenario.

    Unknown enum values become none / neutral / center / all. `say` is trimmed
    to 60 characters, `pause` is clamped to 0..5, steps that do nothing are
    dropped, and the result is capped at 10 steps.
    """
    if not isinstance(raw, dict):
        raise ScenarioError("scenario must be an object")
    title = raw.get("title")
    title = "シナリオ" if title is None else str(title).strip()
    title = title[:30] or "シナリオ"
    steps_in = raw.get("steps")
    if not isinstance(steps_in, list):
        raise ScenarioError("scenario has no steps")
    steps = []
    for item in steps_in:
        if not isinstance(item, dict):
            continue
        step = {key: _enum(item.get(key), key) for key in _ALLOWED}
        step["say"] = _say(item.get("say"))
        step["pause"] = _pause(item.get("pause", 0))
        if _empty(step):
            continue
        steps.append(step)
        if len(steps) == 10:
            break
    if not steps:
        raise ScenarioError("scenario has no steps")
    return {"title": title, "steps": steps}
