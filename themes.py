"""
themes.py — Professional dark visual theme for the PyQt6 interface
====================================================================

This module is responsible for the visual identity of the ENTIRE application.
By centralizing colors, fonts, and styles here, we ensure that any future
visual change is made in a single place and propagates automatically to all widgets.

Usage:
    In app_pyqt.py, after creating the QApplication, call:
        from themes import apply_dark_theme
        apply_dark_theme(app)

    In individual widgets, import the style constants:
        from themes import CARD_STYLE, LABEL_TITLE_STYLE

Design philosophy:
    The dark theme was chosen because:
    1. It reduces eye strain during long clinical sessions.
    2. It increases the contrast of colored charts (PyQtGraph).
    3. It is the de facto standard in modern scientific and medical applications.
    4. The video overlay with a dark background (produced by goniometry_overlay.py)
       integrates naturally and seamlessly with the dark theme.
"""

from PyQt6.QtGui import QColor, QPalette, QFont
from PyQt6.QtWidgets import QApplication


# =============================================================================
# BASE COLOR PALETTE
# =============================================================================
# These constants define the fundamental tones of the theme.
# All styles below derive from these definitions.
# Changing these affects the whole application — use with care.

# Primary window and panel background color.
# #1a1a2e: very dark navy blue. Chosen for being less flat than pure black (#000000)
# and creating visual depth without eye strain.
COLOR_BG_DARK = "#1a1a2e"

# Secondary widget background (cards, groups, inner panels).
# Slightly lighter than BG_DARK to create visual hierarchy without harsh contrast.
COLOR_BG_MEDIUM = "#16213e"

# Background for interactive elements at rest (buttons, text fields).
COLOR_BG_LIGHT = "#0f3460"

# Primary text color — soft white.
# We avoid pure white (#ffffff) because on dark backgrounds it causes visual
# vibration (known as "simultaneous irradiation"). #e2e8f0 is more comfortable.
COLOR_TEXT_PRIMARY = "#e2e8f0"

# Secondary text color — for captions, less important values, placeholders.
COLOR_TEXT_SECONDARY = "#94a3b8"

# Accent color — vibrant cyan blue.
# Used in focus borders, active indicators, and primary action elements.
COLOR_ACCENT = "#38bdf8"

# Success color — green for positive states (hand detected, active session, Regular).
COLOR_SUCCESS = "#22c55e"

# Warning color — yellow for alert states (Good classification, moderate regularity).
COLOR_WARNING = "#eab308"

# Danger color — red for critical states (closed hand, errors, Poor).
COLOR_DANGER = "#ef4444"

# Default border color — dark gray to separate sections without visual aggression.
COLOR_BORDER = "#334155"

# Metric card background color — slightly different from the medium background
# to create visual "elevation" without using shadows (which are costly in PyQt6).
COLOR_CARD_BG = "#1e293b"


# =============================================================================
# MAIN THEME APPLICATION FUNCTION
# =============================================================================

def apply_dark_theme(app: QApplication) -> None:
    """
    Applies the professional dark theme to the QApplication instance.

    This function must be called ONCE, immediately after creating the
    QApplication and BEFORE creating any window or widget. This ensures
    all subsequently created elements inherit the correct theme.

    Qt propagates the QPalette automatically to all child widgets.
    Therefore, configuring only the QApplication palette is sufficient —
    there is no need to set colors per widget individually.

    Parameters:
        app: The QApplication instance created in app_pyqt.py.
             Must be the object returned by QApplication(sys.argv).

    Returns:
        None. The modification is applied directly to the app object.
    """
    # Create a new color palette from scratch to avoid inheriting unexpected
    # values from the operating system's default theme.
    palette = QPalette()

    # --- Color palette definition ---
    # Qt organizes colors by "group" (Normal, Disabled, Inactive) and by "role".
    # We configure only the Normal group — Disabled and Inactive groups inherit
    # automatically with softened tones applied by Qt.

    # Background for main windows (QMainWindow, QDialog).
    palette.setColor(QPalette.ColorRole.Window, QColor(COLOR_BG_DARK))

    # Text on window backgrounds — must have sufficient contrast with Window.
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLOR_TEXT_PRIMARY))

    # Background for input widgets (QLineEdit, QTextEdit, QComboBox).
    # Using BG_MEDIUM to distinguish text fields from the window background.
    palette.setColor(QPalette.ColorRole.Base, QColor(COLOR_BG_MEDIUM))

    # Alternating background in lists and tables (even vs odd rows).
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLOR_BG_LIGHT))

    # Text color inside input fields (QLineEdit, QTextEdit).
    palette.setColor(QPalette.ColorRole.Text, QColor(COLOR_TEXT_PRIMARY))

    # Button background (QPushButton).
    palette.setColor(QPalette.ColorRole.Button, QColor(COLOR_BG_LIGHT))

    # Text on buttons — light for contrast with BG_LIGHT.
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLOR_TEXT_PRIMARY))

    # Accent color: background of selected items, progress bars, etc.
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLOR_ACCENT))

    # Text on accent background — dark to ensure readability
    # when the item is selected (contrast with the cyan blue of Highlight).
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#0f172a"))

    # Text color in disabled fields — darker gray to visually indicate
    # the field is unavailable.
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor("#475569"),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor("#475569"),
    )

    # Color used for tooltips.
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(COLOR_BG_LIGHT))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(COLOR_TEXT_PRIMARY))

    # Apply the configured palette to the entire application.
    # This is the only point where the palette needs to be defined —
    # all subsequently created widgets will inherit it automatically.
    app.setPalette(palette)

    # Apply a global stylesheet to refine elements that QPalette does not control
    # directly. Stylesheet takes precedence over QPalette for the same widgets.
    app.setStyleSheet(_build_global_stylesheet())


def _build_global_stylesheet() -> str:
    """
    Builds and returns the global CSS stylesheet for the application.

    Qt uses a syntax similar to standard CSS to style widgets.
    This function centralizes all styles that require more control
    than QPalette offers (borders, border-radius, padding, hover, etc.).

    Returns:
        str: String containing the full stylesheet in Qt StyleSheet format.
    """
    return f"""
        /* ── Main window ── */
        QMainWindow {{
            background-color: {COLOR_BG_DARK};
        }}

        /* ── Generic widgets ── */
        QWidget {{
            background-color: {COLOR_BG_DARK};
            color: {COLOR_TEXT_PRIMARY};
            font-family: 'Segoe UI', 'Inter', 'Helvetica Neue', sans-serif;
            font-size: 13px;
        }}

        /* ── Widget groups (QGroupBox) ──
           Used as visual containers for each layout section.
           border-radius gives a modern look without being excessive. */
        QGroupBox {{
            background-color: {COLOR_BG_MEDIUM};
            border: 1px solid {COLOR_BORDER};
            border-radius: 8px;
            margin-top: 12px;
            padding: 8px;
            font-weight: bold;
            font-size: 12px;
            color: {COLOR_TEXT_SECONDARY};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 6px;
            color: {COLOR_ACCENT};
        }}

        /* ── Main buttons ──
           Base style with rounded corners. Hover and pressed states
           provide immediate visual feedback on click. */
        QPushButton {{
            background-color: {COLOR_BG_LIGHT};
            color: {COLOR_TEXT_PRIMARY};
            border: 1px solid {COLOR_BORDER};
            border-radius: 6px;
            padding: 8px 18px;
            font-weight: bold;
            min-height: 32px;
        }}
        QPushButton:hover {{
            background-color: {COLOR_ACCENT};
            color: #0f172a;
            border-color: {COLOR_ACCENT};
        }}
        QPushButton:pressed {{
            background-color: #0284c7;
            color: #ffffff;
        }}
        QPushButton:disabled {{
            background-color: #1e293b;
            color: #475569;
            border-color: #1e293b;
        }}

        /* ── Text input fields (QLineEdit) ── */
        QLineEdit {{
            background-color: {COLOR_BG_MEDIUM};
            color: {COLOR_TEXT_PRIMARY};
            border: 1px solid {COLOR_BORDER};
            border-radius: 5px;
            padding: 5px 8px;
            min-height: 28px;
        }}
        QLineEdit:focus {{
            border-color: {COLOR_ACCENT};
        }}
        QLineEdit:disabled {{
            color: #475569;
            background-color: #0f172a;
        }}

        /* ── ComboBox (drop-down lists) ── */
        QComboBox {{
            background-color: {COLOR_BG_MEDIUM};
            color: {COLOR_TEXT_PRIMARY};
            border: 1px solid {COLOR_BORDER};
            border-radius: 5px;
            padding: 4px 8px;
            min-height: 28px;
        }}
        QComboBox:focus {{
            border-color: {COLOR_ACCENT};
        }}
        QComboBox QAbstractItemView {{
            background-color: {COLOR_BG_MEDIUM};
            color: {COLOR_TEXT_PRIMARY};
            selection-background-color: {COLOR_ACCENT};
            selection-color: #0f172a;
            border: 1px solid {COLOR_BORDER};
        }}

        /* ── SpinBox (incremental numeric fields) ── */
        QSpinBox {{
            background-color: {COLOR_BG_MEDIUM};
            color: {COLOR_TEXT_PRIMARY};
            border: 1px solid {COLOR_BORDER};
            border-radius: 5px;
            padding: 4px 8px;
            min-height: 28px;
        }}
        QSpinBox:focus {{
            border-color: {COLOR_ACCENT};
        }}

        /* ── Text area (QTextEdit) — used by LogWidget ── */
        QTextEdit {{
            background-color: #0d1117;
            color: {COLOR_TEXT_SECONDARY};
            border: 1px solid {COLOR_BORDER};
            border-radius: 5px;
            padding: 4px;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 11px;
        }}

        /* ── Scroll bars ──
           Thin and discreet to avoid competing with the main content. */
        QScrollBar:vertical {{
            background: {COLOR_BG_DARK};
            width: 8px;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{
            background: {COLOR_BORDER};
            border-radius: 4px;
            min-height: 20px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {COLOR_ACCENT};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}

        /* ── Horizontal separators (QFrame::HLine) ── */
        QFrame[frameShape="4"] {{
            color: {COLOR_BORDER};
            max-height: 1px;
        }}

        /* ── Generic labels ── */
        QLabel {{
            color: {COLOR_TEXT_PRIMARY};
            background: transparent;
        }}

        /* ── Tooltips ── */
        QToolTip {{
            background-color: {COLOR_BG_LIGHT};
            color: {COLOR_TEXT_PRIMARY};
            border: 1px solid {COLOR_ACCENT};
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
        }}
    """


# =============================================================================
# REUSABLE STYLE CONSTANTS
# =============================================================================
# These StyleSheet strings are imported by individual widgets
# and applied via widget.setStyleSheet(CONSTANT). Centralizing them here avoids
# code duplication and ensures visual consistency across all widgets.

# Base style for metric cards (FPS, CPU, RAM, hand state).
# Used by: ui/metrics_widget.py -> MetricsWidget
# QFrame with slightly lighter background than the panel and subtle border for "elevation".
CARD_STYLE: str = f"""
    .QFrame {{
        background-color: {COLOR_CARD_BG};
        border: 1px solid {COLOR_BORDER};
        border-radius: 8px;
        padding: 8px;
    }}
"""

# Style for the title inside metric cards (e.g., "FPS", "CPU").
# Small text, secondary color — must not compete with the main value.
# Used by: ui/metrics_widget.py -> card labels
LABEL_TITLE_STYLE: str = f"""
    QLabel {{
        color: {COLOR_TEXT_SECONDARY};
        font-size: 11px;
        font-weight: normal;
        background: transparent;
        border: none;
    }}
"""

# Style for the primary numeric value inside cards (e.g., "58.3", "24%").
# Large bold text — must be the most readable element in the card.
# Used by: ui/metrics_widget.py -> card values
LABEL_VALUE_STYLE: str = f"""
    QLabel {{
        color: {COLOR_TEXT_PRIMARY};
        font-size: 22px;
        font-weight: bold;
        background: transparent;
        border: none;
    }}
"""

# Style for the hand state card when HAND OPEN.
# Soft green background — positive indicator, not aggressive.
# Used by: ui/metrics_widget.py -> state card
CARD_HAND_OPEN_STYLE: str = f"""
    .QFrame {{
        background-color: #14532d;
        border: 1px solid {COLOR_SUCCESS};
        border-radius: 8px;
        padding: 8px;
    }}
"""

# Style for the hand state card when HAND CLOSED.
# Dark red background — clinical alert indicator.
# Used by: ui/metrics_widget.py -> state card
CARD_HAND_CLOSED_STYLE: str = f"""
    .QFrame {{
        background-color: #7f1d1d;
        border: 1px solid {COLOR_DANGER};
        border-radius: 8px;
        padding: 8px;
    }}
"""

# Style for the hand state text (large, centered, bold).
# Used by: ui/metrics_widget.py -> label inside the state card
LABEL_HAND_STATE_STYLE: str = f"""
    QLabel {{
        color: {COLOR_TEXT_PRIMARY};
        font-size: 18px;
        font-weight: bold;
        background: transparent;
        border: none;
    }}
"""

# Style for the session header (SessionHeaderWidget).
# Differentiated background to visually separate it from the rest of the layout.
# Used by: ui/session_header.py -> main container
SESSION_HEADER_STYLE: str = f"""
    .QWidget {{
        background-color: {COLOR_BG_MEDIUM};
        border-bottom: 2px solid {COLOR_ACCENT};
    }}
"""

# Style for section title labels inside the header.
# Highlighted text in accent color — clearly identifies the field's purpose.
# Used by: ui/session_header.py -> field labels
LABEL_SECTION_TITLE_STYLE: str = f"""
    QLabel {{
        color: {COLOR_ACCENT};
        font-size: 12px;
        font-weight: bold;
        background: transparent;
    }}
"""

# Style for each finger card (FingerCardWidget).
# More compact than CARD_STYLE — 5 cards fit side by side in the layout.
# Used by: ui/finger_card_widget.py -> each finger container
FINGER_CARD_STYLE: str = f"""
    QGroupBox {{
        background-color: {COLOR_CARD_BG};
        border: 1px solid {COLOR_BORDER};
        border-radius: 8px;
        margin-top: 10px;
        padding: 6px;
    }}
    QGroupBox::title {{
        color: {COLOR_ACCENT};
        font-weight: bold;
        font-size: 12px;
        subcontrol-origin: margin;
        subcontrol-position: top center;
        padding: 0 4px;
    }}
"""

# Style for clinical value labels inside finger cards.
# Medium size — readable but does not dominate the card.
# Used by: ui/finger_card_widget.py -> TAM, velocity, frequency
LABEL_CLINICAL_VALUE_STYLE: str = f"""
    QLabel {{
        color: {COLOR_TEXT_PRIMARY};
        font-size: 14px;
        font-weight: bold;
        background: transparent;
    }}
"""

# Style for secondary metric labels inside finger cards.
# Smaller text — supporting information for the primary value.
# Used by: ui/finger_card_widget.py -> rom, regularity
LABEL_CLINICAL_SECONDARY_STYLE: str = f"""
    QLabel {{
        color: {COLOR_TEXT_SECONDARY};
        font-size: 11px;
        background: transparent;
    }}
"""

# Style for the primary action button (Start Session).
# Highlighted with the success color to indicate a positive and safe action.
# Used by: ui/main_window.py -> Start button
BUTTON_PRIMARY_STYLE: str = f"""
    QPushButton {{
        background-color: #15803d;
        color: #ffffff;
        border: 1px solid {COLOR_SUCCESS};
        border-radius: 6px;
        padding: 8px 18px;
        font-weight: bold;
        min-height: 36px;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background-color: {COLOR_SUCCESS};
        color: #0f172a;
    }}
    QPushButton:pressed {{
        background-color: #166534;
    }}
    QPushButton:disabled {{
        background-color: #1e293b;
        color: #475569;
        border-color: #1e293b;
    }}
"""

# Style for the destructive action button (End Session).
# Red to signal that this action ends the session and cannot easily be undone.
# Used by: ui/main_window.py -> End button
BUTTON_DANGER_STYLE: str = f"""
    QPushButton {{
        background-color: #991b1b;
        color: #ffffff;
        border: 1px solid {COLOR_DANGER};
        border-radius: 6px;
        padding: 8px 18px;
        font-weight: bold;
        min-height: 36px;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background-color: {COLOR_DANGER};
        color: #ffffff;
    }}
    QPushButton:pressed {{
        background-color: #7f1d1d;
    }}
    QPushButton:disabled {{
        background-color: #1e293b;
        color: #475569;
        border-color: #1e293b;
    }}
"""
