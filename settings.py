"""User settings: sensitivity, toggles, per-spell colours and actions (JSON in %APPDATA%)."""
import json
import os

DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "MagicCasterCompanion")

DEFAULTS = {
    "accept": 0.9,            # max DTW distance still counted as a match (lower = stricter)
    "sounds": True,
    "auto_reconnect": True,
    "base_status_light": True,
    "test_mode": False,       # recognise casts but don't run actions
    "colors": {},             # spell -> [r, g, b]
    "actions": {},            # spell -> {"type": ..., "value": ...}
}


class Settings:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(DATA_DIR, "settings.json")
        self.data = json.loads(json.dumps(DEFAULTS))
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                for k, v in saved.items():
                    if k in DEFAULTS and type(v) is type(DEFAULTS[k]):
                        self.data[k] = v
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1)
        except OSError:
            pass

    def get(self, key):
        return self.data[key]

    def set(self, key, value):
        self.data[key] = value
        self.save()

    # per-spell colour
    def color(self, spell):
        c = self.data["colors"].get(spell)
        if isinstance(c, list) and len(c) == 3:
            return tuple(int(x) & 255 for x in c)
        return None

    def set_color(self, spell, rgb):
        if rgb is None:
            self.data["colors"].pop(spell, None)
        else:
            self.data["colors"][spell] = [int(x) for x in rgb]
        self.save()

    # per-spell action
    def action(self, spell):
        a = self.data["actions"].get(spell)
        return a if isinstance(a, dict) and a.get("type") not in (None, "", "None") else None

    def set_action(self, spell, action):
        if not action or action.get("type") in (None, "", "None"):
            self.data["actions"].pop(spell, None)
        else:
            self.data["actions"][spell] = {"type": action["type"], "value": action.get("value", "")}
        self.save()
