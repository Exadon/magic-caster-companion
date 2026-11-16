"""Spell catalogue: names, short descriptions, gesture diagrams, light/buzz effects."""
import colorsys
import hashlib
import re
import os
import sys


def resource_path(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


# Spells that have a gesture diagram in assets/gestures (extra files like typos are ignored).
_IGNORED = {"colvaria", "entomorphls", "immobulus_spell_path_two", "immobulus_two"}
# Extra spells the wand supports without a bundled diagram.
_EXTRA = """avada_kedavra cantis descendo langlock locomotor pestis_incendium sonorus spongify
the_hour_reversal_reversal_charm the_pepper_breath_hex""".split()

# One-line descriptions, only where the canon effect is well known.
DESCRIPTIONS = {
    "aberto": "Opens doors and other closed things.",
    "accio": "The Summoning Charm: brings a distant object to you.",
    "aguamenti": "Conjures a jet of clean water from the wand.",
    "alohomora": "The Unlocking Charm.",
    "anteoculatia": "Makes antlers sprout from the target's head.",
    "arania_exumai": "Drives spiders away.",
    "ascendio": "Lifts the caster up into the air.",
    "bombarda": "Creates a small explosion to blast obstacles apart.",
    "brachiabindo": "Binds the target's arms.",
    "calvorio": "Removes the target's hair.",
    "colloportus": "Locks a door and magically seals it.",
    "colloshoo": "Sticks the target's shoes to the floor.",
    "colovaria": "Changes the colour of the target.",
    "confringo": "The Blasting Curse: sets its target aflame and blows it apart.",
    "confundo": "The Confundus Charm: confuses the target.",
    "densaugeo": "Makes the target's teeth grow rapidly.",
    "entomorphis": "Turns the target into an insect.",
    "evanesco": "Vanishes the target.",
    "expecto_patronum": "Conjures a Patronus, a guardian made of silvery light.",
    "expelliarmus": "The Disarming Charm: sends the target's wand flying.",
    "expulso": "Blasts the target away with an explosive force.",
    "finestra": "Shatters windows and glass.",
    "finite": "Ends the effect of another spell.",
    "flagrate": "Draws glowing fiery marks in the air.",
    "flipendo": "The Knockback Jinx: pushes the target away.",
    "glacius": "Freezes the target in ice.",
    "herbivicus": "Makes plants grow quickly.",
    "immobulus": "Freezes the target in place.",
    "impedimenta": "The Impediment Jinx: slows or stops the target.",
    "incarcerous": "Binds the target with ropes.",
    "incendio": "Conjures flames.",
    "lumos": "Lights the tip of the wand.",
    "lumos_maxima": "Casts a much brighter light.",
    "melefors": "The Pumpkin-Head Jinx.",
    "mucus_ad_nauseum": "Gives the target a streaming, uncontrollable runny nose.",
    "nox": "Puts out the light from Lumos.",
    "orchideous": "Conjures a bouquet of flowers.",
    "petrificus_totalus": "The Full Body-Bind Curse: locks the target's body rigid.",
    "piertotum_locomotor": "Brings statues and suits of armour to life.",
    "protego": "The Shield Charm: deflects spells and light jinxes.",
    "quietus": "Makes a magnified voice quiet again.",
    "reducto": "The Reductor Curse: blasts solid objects into pieces.",
    "reparo": "Mends broken objects.",
    "revelio": "Reveals hidden objects and secrets.",
    "rictusempra": "The Tickling Charm.",
    "riddikulus": "Turns a Boggart into something funny.",
    "scourgify": "Cleans a surface of dirt and grime.",
    "silencio": "The Silencing Charm: makes the target silent.",
    "stupefy": "The Stunning Spell: knocks the target out.",
    "the_cheering_charm": "Fills the target with happiness.",
    "the_sleeping_charm": "Puts the target to sleep.",
    "ventus": "Conjures a strong gust of wind.",
    "verdimillious": "Shoots green sparks into the air.",
    "vermillious": "Shoots red sparks into the air.",
    "wingardium_leviosa": "The Levitation Charm: makes objects float.",
}

CAST_STEPS = (
    "1. Hold the wand firmly and keep it still for a moment.\n"
    "2. Start at the dot and trace the arrows in the air, at a smooth, steady pace.\n"
    "3. Finish the stroke, then stop and hold still. When the book recognises your "
    "motion, the wand lights up and buzzes.\n"
    "4. Use big, deliberate motions: the wand senses movement, not where it points.\n"
    "5. The book learns from you: record a few casts of each spell on the Cast page."
)


def spell_key(name: str) -> str:
    """Normalise a spell name from the wand ('Wingardium Leviosa', 'The_Stretching_Jinx') to our ids."""
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")


def pretty(s: str) -> str:
    return s.replace("_", " ").title().replace("Of ", "of ")


def _diagrams() -> dict:
    d = resource_path(os.path.join("assets", "gestures"))
    out = {}
    try:
        for f in os.listdir(d):
            stem, ext = os.path.splitext(f)
            if ext == ".png" and stem not in _IGNORED:
                out[stem] = os.path.join(d, f)
    except OSError:
        pass
    # Spells with a second drawn path
    alt = os.path.join(d, "immobulus_two.png")
    if os.path.exists(alt):
        out["immobulus"] = [out.get("immobulus"), alt]
    return out


DIAGRAMS = _diagrams()
SPELLS = sorted(set(DIAGRAMS) | set(_EXTRA))


def diagram_paths(name: str):
    v = DIAGRAMS.get(name)
    if v is None:
        return []
    return [p for p in (v if isinstance(v, list) else [v]) if p]


def spell_color(name: str):
    h = int(hashlib.md5(name.encode()).hexdigest()[:4], 16) / 0xFFFF
    r, g, b = colorsys.hsv_to_rgb(h, 0.85, 1.0)
    return int(r * 255), int(g * 255), int(b * 255)


def spell_effect(name: str, color=None):
    r, g, b = color or spell_color(name)
    return [("buzz", 200), ("led", 0, r, g, b, 300), ("led", 1, r // 2, g // 2, b // 2, 250),
            ("delay", 700), ("clear",)]
