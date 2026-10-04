"""Vocabulary and JSON schema for an AI-generated stage scenario.

The local 3B model picks words from these enums. Cell coordinates are computed
later in formations.py; they are intentionally absent from the schema.
"""

FACES = ("neutral", "happy", "angry", "sad", "doubt", "sleepy")
LOOKS = ("center", "left", "right", "up", "down", "toio")
BODIES = ("none", "wiggle", "turn_left", "turn_right", "nod", "dance")
TOIO_MOVES = (
    "none",
    "square", "circle", "line", "heart", "x", "scatter", "home",
    "spin", "wiggle", "wave",
)
TOIO_GROUPS = ("all", "odd", "even")
TOIO_COLORS = ("none", "red", "green", "blue", "yellow", "purple", "white", "rainbow", "off")
TOIO_SOUNDS = ("none", "ok", "ng", "cheer", "beep")

# Coercion targets when the model (or a hand-edited file) leaves the enum.
DEFAULTS = {
    "face": "neutral",
    "look": "center",
    "body": "none",
    "toio_move": "none",
    "toio_group": "all",
    "toio_color": "none",
    "toio_sound": "none",
}

FORMATIONS = ("square", "circle", "line", "heart", "x", "scatter", "home")
DANCES = ("spin", "wiggle", "wave")
STEP_KEYS = (
    "say", "face", "look", "body", "toio_move", "toio_group", "toio_color", "toio_sound", "pause",
)


def _enum(values):
    return {"type": "string", "enum": list(values)}


SCENARIO_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "steps"],
    "properties": {
        "title": {"type": "string", "maxLength": 30},
        "steps": {
            "type": "array",
            "minItems": 3,
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": list(STEP_KEYS),
                "properties": {
                    "say": {"type": "string", "maxLength": 40},
                    "face": _enum(FACES),
                    "look": _enum(LOOKS),
                    "body": _enum(BODIES),
                    "toio_move": _enum(TOIO_MOVES),
                    "toio_group": _enum(TOIO_GROUPS),
                    "toio_color": _enum(TOIO_COLORS),
                    "toio_sound": _enum(TOIO_SOUNDS),
                    "pause": {"type": "integer", "minimum": 0, "maximum": 5},
                },
            },
        },
    },
}
