"""Centralised colour palette and layout constants for the cluster UI.

Every widget pulls its colours and shared dimensions from here so the whole
cluster can be restyled in one place.
"""

# --- Colours (RGBA, 0..1) ---
ACCENT = (0.2392, 0.4588, 0.6588, 1.0)   # card / dial accent blue
FG = (1.0, 1.0, 1.0, 1.0)                # default foreground / text
WARNING = (1.0, 0.0, 0.0, 1.0)           # over-threshold red
DARK = (0.1, 0.1, 0.1, 1.0)              # dial face / inactive fill
NEEDLE = (0.9882, 0.2471, 0.1490, 1.0)   # gauge needle
INDICATOR_ON = (0.0, 1.0, 0.0, 1.0)      # turn indicator active (green)
INDICATOR_OFF = (0.1, 0.1, 0.1, 1.0)     # turn indicator inactive
REDLINE = (1.0, 0.0, 0.0, 0.5)           # gauge redline arc

# --- Minimal "Painel Gol" theme (dark, Azul Boreal accent) ---
BG = (0.0, 0.0, 0.0, 1.0)                # pure-black page background (contrast)
TEXT = (0.925, 0.933, 0.949, 1.0)        # #eceef2 primary text
VALUE = (1.0, 1.0, 1.0, 0.82)            # default readout value
LABEL_DIM = (0.353, 0.651, 0.918, 0.70)  # micro-grid labels (accent)
LABEL_ACCENT = (0.353, 0.651, 0.918, 0.95)  # big section labels (BOOST/LAMBDA)
UNIT_DIM = (0.353, 0.651, 0.918, 0.45)   # units / tags under big values
HAIRLINE = (0.353, 0.651, 0.918, 0.28)   # thin divider lines (accent)
BOOST_NORMAL = (0.420, 0.706, 0.945, 1.0)  # Azul Boreal boost (in range)

# tell-tale (top alert) colours, by ISO convention
TT_GREEN = (0.200, 0.819, 0.478, 1.0)    # #33d17a turn signals
TT_BLUE = (0.353, 0.651, 0.918, 1.0)     # #5aa6ea high beam
TT_RED = (1.000, 0.353, 0.271, 1.0)      # #ff5a45 oil / batt / temp / brake
TT_AMBER = (1.000, 0.690, 0.180, 1.0)    # #ffb02e cel / fuel
TT_CYAN = (0.133, 0.827, 0.933, 1.0)     # #22d3ee 2-step
TT_BOOST = (1.000, 0.231, 0.188, 1.0)    # #ff3b30 over-boost
PILL_OFF_BORDER = (1.0, 1.0, 1.0, 0.06)  # tell-tale outline when inactive
PILL_OFF_TEXT = (1.0, 1.0, 1.0, 0.10)    # tell-tale label when inactive

# lambda value colours
LAMBDA_RICH = (1.000, 0.541, 0.302, 1.0)   # #ff8a4d
LAMBDA_LEAN = (1.000, 0.819, 0.302, 1.0)   # #ffd14d
LAMBDA_STOICH = (0.498, 0.839, 0.639, 1.0)  # #7fd6a3

# EGT per-cylinder balance readout (4 dots): green when a channel is in line with
# the others, reddening as it deviates from the group median.
EGT_BALANCED = (0.200, 0.819, 0.478, 1.0)    # #33d17a in-balance (green)
EGT_MID = (1.000, 0.780, 0.231, 1.0)         # #ffc73b mid-deviation (amber) gradient stop
EGT_UNBALANCED = (1.000, 0.231, 0.188, 1.0)  # #ff3b30 deviating (red)
EGT_INACTIVE = (0.353, 0.651, 0.918, 0.16)   # faint dot when no EGT data
EGT_SPREAD_RED = 100.0   # °C deviation from the median that reads as fully red
EGT_ACTIVE_MIN = 80.0    # below this (cold / engine off) the readout is inactive

# critical alarm banner (lean / overheat / oil pressure)
ALARM_BG = (0.86, 0.07, 0.05, 1.0)         # vivid red banner
ALARM_TEXT = (1.0, 1.0, 1.0, 1.0)          # white alarm text

# minimal gauge styling (Azul Boreal accent leans heavier on the blue)
GAUGE_FACE = (0.0, 0.0, 0.0, 1.0)          # pure-black dial face (ring separates)
GAUGE_RING = (0.353, 0.651, 0.918, 0.28)   # blue disc edge ring
GAUGE_TICK = (0.667, 0.804, 0.945, 0.92)   # major ticks (cool white-blue)
GAUGE_TICK_MINOR = (0.353, 0.651, 0.918, 0.28)  # minor ticks (faint blue)
GAUGE_NUM = (0.700, 0.820, 0.945, 0.62)    # dial numerals (cool)
GAUGE_ARC = (0.353, 0.651, 0.918, 0.85)    # bold progress arc (Azul Boreal)
GAUGE_NEEDLE = (0.353, 0.651, 0.918, 1.0)  # #5aa6ea needle
GAUGE_REDLINE = (1.0, 0.353, 0.314, 0.85)  # softer redline arc
GAUGE_SHIFT = (1.0, 0.824, 0.227, 1.0)     # #ffd23a shift-flash arc/needle (amber)
GAUGE_SHIFT_TEXT = (1.0, 0.231, 0.188, 1.0)  # #ff3b30 "SHIFT!" text (red)
GAUGE_SHIFT_FLASH = (1.0, 0.094, 0.063, 1.0)  # red disc wash strobed during shift
GAUGE_CENTER = (0.949, 0.957, 0.973, 1.0)  # #f2f4f8 centre digit
GAUGE_SUB = (0.353, 0.651, 0.918, 0.85)    # SPEED / RPM sub-label (accent)
GAUGE_UNIT = (0.353, 0.651, 0.918, 0.40)   # km/h / x1000 unit (faint accent)

# fonts (paths are usable directly as Kivy `font_name`)
FONT_MONO = "fonts/ShareTechMono-Regular.ttf"   # labels / units
FONT_LIGHT = "fonts/Compagnon-Light.otf"        # big numerals (light weight)
FONT_ICONS = "fonts/materialdesignicons-webfont.ttf"  # tell-tale glyphs (MDI)

# --- Window ---
WINDOW_WIDTH = 1920
WINDOW_HEIGHT = 720

# --- Centre card (engine info + shift banner share these) ---
CARD_WIDTH = 450
CARD_HEIGHT = 600
CARD_RADIUS = 20
