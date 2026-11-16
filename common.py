"""Shared imports, layout constants and small helpers used by the app's modules."""
import asyncio
import collections
import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk
from tkinter import font as tkfont

from PIL import Image, ImageTk

import gestures
from actions import ACTION_TYPES, HINTS, play_cue, run_action, validate
from gestures import UNLOCK_AT
from mcwand import Box, LED_GROUPS, Wand, scan
from practice import PracticeStats, evaluate, pick_target
from settings import DATA_DIR, Settings
from sounds import STYLE_LABELS, STYLES
from spells_data import (CAST_STEPS, DESCRIPTIONS, SPELLS, diagram_paths, pretty, resource_path,
                         spell_color, spell_effect, spell_key)
from ui_kit import (CARD, CARD_EDGE, FIELD, GOLD, INK, LEATHER, PARCH, PARCH_DARK, RED, SERIF,
                    RoundButton, Tip, apply_styles, battery_color, battery_percent, ink_image, make_leather,
                    make_page, state_color, style_titlebar, tab_pil)
from version import __version__
from voice import VoiceListener
from voice import available as voice_available
from voice import phrase_map
from winintegration import SingleInstance, Tray, autostart_enabled, set_autostart

W, H = 1000, 730
BX0, BX1, BY0, BY1 = 30, 930, 25, 675
SPINE = (BX0 + BX1) // 2
LX, RX = BX0 + 28, SPINE + 28          # left/right page content origins
PAGE_W = SPINE - BX0 - 56              # usable content width of a page
SX0, SX1 = BX0 + 36, BX1 - 36          # content edges of a full two-page spread
RETRY_S = 6                            # seconds between automatic reconnect attempts
MUTED = "#7a6a4a"

TABS = [("devices", "Devices", "#8a2323"), ("spells", "Spells", "#2f6b3a"), ("teach", "Teach", "#1f6b72"),
        ("practice", "Practice", "#b5541f"), ("cast", "Cast", "#243f73"), ("lights", "Lights", "#b8862b"),
        ("notes", "Notes", "#5a2f6b")]
MARK = {"unlocked": "✦ ", "learning": "◇ ", "locked": "   "}
FIRE_WINDOW_S = 2.5   # the wand and the book seeing the same cast within this window count as one cast
STATE_TEXT = {"unlocked": "✦ Unlocked", "learning": "◇ Learning", "locked": "Locked"}
VOICE_MODES = [("off", "Off"), ("motion", "Voice + a swish of the wand"), ("voice", "Voice only")]
VOICE_WINDOW_S = 3.0  # a spoken spell and a swish of the wand must happen within this many seconds


def hexcolor(rgb):
    return "#%02x%02x%02x" % tuple(int(x) for x in rgb)
