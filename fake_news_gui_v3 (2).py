"""
Fake News Dataset Explorer - GUI Version 3 (Premium Analytics Edition)
========================================================================
Project #26: Fake News Dataset Explorer

This is a full rebuild of fake_news_gui_v2.py. Every feature from v2 is
preserved and working; the interface, architecture, and reliability have
been substantially upgraded.

What changed vs v2
-------------------
- Premium application shell: collapsible dark sidebar with grouped nav,
  a top header with live dataset status, and a bottom status bar.
- Dashboard rebuilt as a real KPI + chart overview with auto-generated
  insights (nothing hard-coded - every number is computed from self.df).
- Every page redesigned with card-based layout, a shared color system
  (Fake = coral/red, Real = teal/green, always, everywhere), and a
  centralized matplotlib style so all charts look consistent.
- Search gained Subject / Min words / Max words filters and now opens a
  full Article Detail window on double-click (title, meta, full text,
  copy button) instead of only showing a truncated title in a table.
- Top/Bottom Records split into two clear cards, also double-clickable.
- Export now uses a real "Save As" dialog, shows what cleaning steps
  were applied (with real counts), and confirms success in a toast
  instead of a static label.
- Robust error handling: missing/corrupt CSVs, missing columns, empty
  datasets, and bad dates never crash the app or show a raw traceback -
  they show a plain-language message. Unexpected errors are caught at
  the top level too and logged to fake_news_gui_error.log.
- Background threads for the slow operations (initial load, search,
  word-frequency counting, CSV export) so the UI never freezes; only
  the main thread ever touches Tk widgets.
- Pages are now built lazily (on first visit) and cached, so navigating
  around the app repeatedly does not rebuild charts or leak widgets.
- Sortable result tables, alternating row colors, colored Fake/Real
  badges, and a resizable layout that holds up from 1150x720 up to
  1920x1080.

Requirements:
    pip install pandas numpy matplotlib ttkbootstrap

How to run:
    1. Put Fake.csv and True.csv in the SAME FOLDER as this script.
    2. Run:  python fake_news_gui_v3.py
"""

import os
import re
import sys
import csv
import queue
import traceback
import threading
from collections import Counter
from datetime import datetime

import pandas as pd
import numpy as np

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import ttkbootstrap as tb
from ttkbootstrap.constants import *

try:
    from ttkbootstrap.tooltip import ToolTip
except Exception:  # pragma: no cover - keep app usable even if unavailable
    ToolTip = None


# ============================================================================
# 0. LOGGING (so a normal user never sees a raw traceback)
# ============================================================================

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_news_gui_error.log")


def log_exception(context, exc):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now().isoformat()}] {context}\n")
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except Exception:
        pass  # logging must never itself crash the app


# ============================================================================
# 1. DESIGN SYSTEM - colors, fonts, and shared chart styling
# ============================================================================

COLORS = {
    "fake": "#E4572E",
    "fake_soft": "#FBE2DA",
    "real": "#2E8B57",
    "real_soft": "#DCEEE3",
    "accent": "#3B82F6",
    "accent_soft": "#DDE9FE",
    "warning": "#F59E0B",
    "neutral": "#64748B",
    "page_bg": "#F1F5F9",
    "card_bg": "#FFFFFF",
    "card_border": "#E2E8F0",
    "sidebar_bg": "#101826",
    "sidebar_hover": "#1B2536",
    "sidebar_active": "#22314A",
    "sidebar_text": "#CBD5E1",
    "sidebar_text_muted": "#64748B",
    "sidebar_text_active": "#FFFFFF",
    "text_primary": "#0F172A",
    "text_secondary": "#64748B",
    "success": "#16A34A",
    "danger": "#DC2626",
}

FONT_FAMILY = "Segoe UI"

plt.rcParams.update({
    "font.family": FONT_FAMILY,
    "font.size": 10,
    "figure.dpi": 108,
    "axes.edgecolor": "#CBD5E1",
    "axes.linewidth": 0.9,
    "figure.facecolor": COLORS["card_bg"],
    "axes.facecolor": COLORS["card_bg"],
    "savefig.facecolor": COLORS["card_bg"],
})


def style_axes(ax, fig, title=None, xlabel=None, ylabel=None):
    """Central chart style so every chart in the app looks the same."""
    fig.patch.set_facecolor(COLORS["card_bg"])
    ax.set_facecolor(COLORS["card_bg"])
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color("#CBD5E1")
    ax.tick_params(colors="#475569", labelsize=9)
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, fontsize=13, fontweight="bold", color=COLORS["text_primary"], pad=12)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=10, color="#334155")
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=10, color="#334155")


def label_color(label):
    return COLORS["fake"] if label == "Fake" else COLORS["real"]


# ============================================================================
# 2. DATA LOADING AND CLEANING
# ============================================================================

class DataLoadError(Exception):
    """Raised for any problem loading/cleaning the dataset. Carries a
    plain-language title + detail so the UI can show a friendly dialog."""
    def __init__(self, title, detail):
        super().__init__(detail)
        self.title = title
        self.detail = detail


REQUIRED_COLUMNS = ["title", "text", "subject", "date"]

STOPWORDS = set([
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with',
    'is', 'are', 'was', 'were', 'be', 'been', 'being', 'it', 'this', 'that', 'as',
    'by', 'from', 'has', 'have', 'had', 'not', 'said', 'will', 'would', 'he', 'she',
    'they', 'their', 'his', 'her', 'you', 'your', 'we', 'i', 'its', 'who',
    'what', 'which', 'when', 'where', 'why', 'how', 'all', 'than', 'also', 'so',
    'if', 'no', 'out', 'up', 'about', 'into', 'over', 'after', 'more', 'one',
    'new', 'two', 'time', 'like', 'just', 'now', 'can', 'could', 'should', 'while',
])


def load_and_clean_data(status_cb=None):
    """Loads Fake.csv / True.csv, cleans them, and returns (df, meta).
    Raises DataLoadError with a friendly message on any problem.
    status_cb(str) is called with progress messages if provided.
    """
    def report(msg):
        if status_cb:
            status_cb(msg)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    fake_path = os.path.join(base_dir, "Fake.csv")
    real_path = os.path.join(base_dir, "True.csv")

    report("Looking for dataset files...")
    missing = [name for name, p in (("Fake.csv", fake_path), ("True.csv", real_path))
               if not os.path.exists(p)]
    if missing:
        raise DataLoadError(
            "Dataset files not found",
            "Could not find " + " and ".join(missing) + f" in:\n{base_dir}\n\n"
            "Place both files in the same folder as this script and restart the app."
        )

    report("Reading CSV files...")
    try:
        fake_df = pd.read_csv(fake_path)
        real_df = pd.read_csv(real_path)
    except (pd.errors.ParserError, csv.Error, UnicodeDecodeError) as e:
        raise DataLoadError("Could not read the CSV files", f"The files appear to be corrupted or "
                             f"not valid CSV.\n\nDetails: {e}")
    except Exception as e:
        raise DataLoadError("Could not read the CSV files", str(e))

    for name, frame in (("Fake.csv", fake_df), ("True.csv", real_df)):
        missing_cols = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
        if missing_cols:
            raise DataLoadError(
                f"{name} is missing required columns",
                f"Expected columns {REQUIRED_COLUMNS}.\nMissing: {missing_cols}"
            )

    report("Merging Fake + True datasets...")
    fake_df = fake_df.copy()
    real_df = real_df.copy()
    fake_df["label"] = "Fake"
    real_df["label"] = "Real"
    raw_count = len(fake_df) + len(real_df)

    df = pd.concat([fake_df, real_df], ignore_index=True)

    report("Removing duplicate rows...")
    before_dupes = len(df)
    df = df.drop_duplicates()
    dupes_removed = before_dupes - len(df)

    report("Removing rows with missing article text...")
    before_missing = len(df)
    df = df.dropna(subset=["text"])
    df = df[df["text"].astype(str).str.strip() != ""]
    df = df.reset_index(drop=True)
    missing_removed = before_missing - len(df)

    if df.empty:
        raise DataLoadError(
            "Dataset is empty after cleaning",
            "No usable rows remained after removing duplicates and empty articles. "
            "Please check that Fake.csv / True.csv contain valid data."
        )

    report("Calculating article lengths...")
    df["text_length"] = df["text"].astype(str).apply(lambda x: len(x.split()))

    report("Parsing publication dates...")
    df["date_parsed"] = pd.to_datetime(df["date"].astype(str).str.strip(),
                                        errors="coerce", format="mixed")

    df["subject"] = df["subject"].fillna("Unknown").astype(str).str.strip()
    df["subject"] = df["subject"].replace("", "Unknown")
    df["title"] = df["title"].fillna("(untitled)").astype(str)

    clean_count = len(df)
    retention = (clean_count / raw_count * 100) if raw_count else 0.0
    valid_dates = int(df["date_parsed"].notna().sum())

    meta = {
        "raw_count": raw_count,
        "clean_count": clean_count,
        "dupes_removed": dupes_removed,
        "missing_removed": missing_removed,
        "retention": retention,
        "valid_dates": valid_dates,
    }
    report("Ready.")
    return df, meta


def get_common_words(text_series, n=15):
    words = []
    for text in text_series:
        cleaned = re.sub(r'[^a-zA-Z\s]', '', str(text).lower())
        words.extend([w for w in cleaned.split() if w not in STOPWORDS and len(w) > 2])
    return Counter(words).most_common(n)


# ============================================================================
# 3. REUSABLE UI COMPONENTS
# ============================================================================

def create_card(parent, padding=18, bg=COLORS["card_bg"]):
    """Returns (outer, content). Pack/grid `outer`; put widgets in `content`.
    Gives a flat card the appearance of a thin border + subtle elevation."""
    shadow = tk.Frame(parent, bg="#D7DEE7")
    outer = tk.Frame(shadow, bg=COLORS["card_border"])
    outer.pack(fill=BOTH, expand=True, padx=(0, 2), pady=(0, 2))
    inner = tk.Frame(outer, bg=bg)
    inner.pack(fill=BOTH, expand=True, padx=1, pady=1)
    content = tk.Frame(inner, bg=bg, padx=padding, pady=padding)
    content.pack(fill=BOTH, expand=True)
    return shadow, content


def create_page_header(parent, title, subtitle=None):
    wrap = tk.Frame(parent, bg=COLORS["page_bg"])
    wrap.pack(fill=X, pady=(0, 18))
    tk.Label(wrap, text=title, font=(FONT_FAMILY, 19, "bold"),
              bg=COLORS["page_bg"], fg=COLORS["text_primary"]).pack(anchor="w")
    if subtitle:
        tk.Label(wrap, text=subtitle, font=(FONT_FAMILY, 10),
                  bg=COLORS["page_bg"], fg=COLORS["text_secondary"]).pack(anchor="w", pady=(3, 0))
    return wrap


def create_kpi_card(parent, icon, value, title, subtitle=None, accent=COLORS["accent"]):
    shadow, content = create_card(parent, padding=16)
    top = tk.Frame(content, bg=COLORS["card_bg"])
    top.pack(fill=X)
    tk.Label(top, text=icon, font=(FONT_FAMILY, 15), bg=COLORS["card_bg"], fg=accent).pack(side=LEFT)
    tk.Label(content, text=value, font=(FONT_FAMILY, 22, "bold"),
              bg=COLORS["card_bg"], fg=COLORS["text_primary"]).pack(anchor="w", pady=(10, 0))
    tk.Label(content, text=title, font=(FONT_FAMILY, 10),
              bg=COLORS["card_bg"], fg=COLORS["text_secondary"]).pack(anchor="w")
    if subtitle:
        tk.Label(content, text=subtitle, font=(FONT_FAMILY, 9, "bold"),
                  bg=COLORS["card_bg"], fg=accent).pack(anchor="w", pady=(6, 0))
    return shadow


def create_section_card(parent, title=None):
    """A card meant to hold a chart or a block of content."""
    shadow, content = create_card(parent, padding=16)
    if title:
        tk.Label(content, text=title, font=(FONT_FAMILY, 12, "bold"),
                  bg=COLORS["card_bg"], fg=COLORS["text_primary"]).pack(anchor="w", pady=(0, 10))
    return shadow, content


def create_chart_container(parent, title=None):
    shadow, content = create_section_card(parent, title=title)
    chart_area = tk.Frame(content, bg=COLORS["card_bg"])
    chart_area.pack(fill=BOTH, expand=True)
    return shadow, chart_area


def create_badge(parent, text, kind="neutral"):
    palette = {
        "fake": (COLORS["fake_soft"], COLORS["fake"]),
        "real": (COLORS["real_soft"], COLORS["real"]),
        "neutral": ("#EEF2F7", COLORS["neutral"]),
    }
    bg, fg = palette.get(kind, palette["neutral"])
    return tk.Label(parent, text=text, font=(FONT_FAMILY, 9, "bold"), bg=bg, fg=fg,
                     padx=10, pady=3)


def show_empty_state(parent, icon, title, message):
    wrap = tk.Frame(parent, bg=COLORS["card_bg"])
    wrap.pack(fill=BOTH, expand=True, pady=40)
    tk.Label(wrap, text=icon, font=(FONT_FAMILY, 34), bg=COLORS["card_bg"],
              fg=COLORS["neutral"]).pack()
    tk.Label(wrap, text=title, font=(FONT_FAMILY, 13, "bold"), bg=COLORS["card_bg"],
              fg=COLORS["text_primary"]).pack(pady=(10, 4))
    tk.Label(wrap, text=message, font=(FONT_FAMILY, 10), bg=COLORS["card_bg"],
              fg=COLORS["text_secondary"], wraplength=460, justify="center").pack()
    return wrap


def show_error_state(parent, title, message):
    return show_empty_state(parent, "⚠️", title, message)


def show_success_toast(root, message):
    toast = tk.Toplevel(root)
    toast.overrideredirect(True)
    toast.attributes("-topmost", True)
    frame = tk.Frame(toast, bg=COLORS["success"], padx=16, pady=10)
    frame.pack()
    tk.Label(frame, text="✓ " + message, bg=COLORS["success"], fg="white",
              font=(FONT_FAMILY, 10, "bold")).pack()
    root.update_idletasks()
    x = root.winfo_rootx() + root.winfo_width() - 340
    y = root.winfo_rooty() + root.winfo_height() - 90
    toast.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    toast.after(2600, toast.destroy)


def create_table(parent, columns, headings, widths, height=14):
    """Returns (wrapper_frame, treeview). Adds scrollbar + alternating
    rows + sortable headers automatically."""
    wrapper = tk.Frame(parent, bg=COLORS["card_bg"])
    tree = ttk.Treeview(wrapper, columns=columns, show="headings", height=height)
    vsb = ttk.Scrollbar(wrapper, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vsb.set)

    for col, head, width in zip(columns, headings, widths):
        tree.heading(col, text=head, command=lambda c=col, t=tree: sort_table(t, c, False))
        tree.column(col, width=width, anchor="w")

    tree.tag_configure("oddrow", background="#F8FAFC")
    tree.tag_configure("evenrow", background=COLORS["card_bg"])
    tree.tag_configure("fake", foreground=COLORS["fake"])
    tree.tag_configure("real", foreground=COLORS["real"])

    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    wrapper.grid_rowconfigure(0, weight=1)
    wrapper.grid_columnconfigure(0, weight=1)

    tree.row_data = {}
    return wrapper, tree


def sort_table(tree, col, descending):
    items = [(tree.set(iid, col), iid) for iid in tree.get_children("")]

    def sort_key(pair):
        val = pair[0]
        try:
            return (0, float(val.replace(",", "")))
        except (ValueError, AttributeError):
            return (1, str(val).lower())

    items.sort(key=sort_key, reverse=descending)
    for index, (_, iid) in enumerate(items):
        tree.move(iid, "", index)
    tree.heading(col, command=lambda: sort_table(tree, col, not descending))


def populate_table(tree, rows, row_to_values, row_key=None):
    """rows: iterable of pandas Series/dict-like. row_to_values(row) -> tuple
    of display values. Stores the original row on tree.row_data for use by
    double-click handlers."""
    for iid in tree.get_children():
        tree.delete(iid)
    tree.row_data = {}
    for i, row in enumerate(rows):
        values = row_to_values(row)
        label = row.get("label") if hasattr(row, "get") else None
        tags = []
        tags.append("evenrow" if i % 2 == 0 else "oddrow")
        if label == "Fake":
            tags.append("fake")
        elif label == "Real":
            tags.append("real")
        iid = tree.insert("", "end", values=values, tags=tuple(tags))
        tree.row_data[iid] = row


# ============================================================================
# 4. BACKGROUND WORK HELPER (keeps Tk calls on the main thread)
# ============================================================================

def run_in_background(root, work_fn, on_done, on_error=None):
    """Runs work_fn() on a worker thread; marshals the result (or error)
    back onto the Tk main thread via root.after(0, ...)."""
    def worker():
        try:
            result = work_fn()
        except Exception as e:
            log_exception("background task", e)
            root.after(0, lambda: (on_error(e) if on_error else None))
            return
        root.after(0, lambda: on_done(result))
    threading.Thread(target=worker, daemon=True).start()


# ============================================================================
# 5. MAIN APPLICATION
# ============================================================================

class FakeNewsExplorerApp:

    SECTIONS = [
        ("OVERVIEW", [("dashboard", "Dashboard", "🏠")]),
        ("ANALYTICS", [
            ("category", "Category Distribution", "📊"),
            ("length", "Text Length", "📏"),
            ("source", "Source Comparison", "🗂"),
            ("words", "Common Words", "🔤"),
            ("trend", "Trend Analysis", "📈"),
        ]),
        ("EXPLORATION", [
            ("topbottom", "Top / Bottom Records", "🔝"),
            ("search", "Search Articles", "🔎"),
        ]),
        ("OUTPUT", [("export", "Export Dataset", "💾")]),
    ]

    PAGE_META = {
        "dashboard": ("Dashboard Overview", "Explore the structure, distribution, and statistical characteristics of the loaded news dataset."),
        "category": ("Category Distribution", "Understand how Fake and Real articles are distributed across the dataset."),
        "length": ("Text Length Analysis", "Compare article length between Fake and Real news."),
        "source": ("Source (Subject) Comparison", "Compare how Fake and Real articles are spread across each reported subject."),
        "words": ("Common Words", "Explore the most frequent words used across the dataset."),
        "trend": ("Monthly Trends", "Observe how Fake and Real news article volume varies over time."),
        "topbottom": ("Top / Bottom Records", "The longest and shortest articles in the dataset by word count."),
        "search": ("Search Articles", "Search and filter the full dataset by keyword, label, subject, and length."),
        "export": ("Export Dataset", "Save the cleaned and processed dataset for further analysis."),
    }

    def __init__(self, root, df, meta):
        self.root = root
        self.df = df
        self.meta = meta
        self.current_page = None
        self.pages = {}          # key -> built page frame (lazy, cached)
        self.nav_items = {}      # key -> NavItem
        self.sidebar_collapsed = False

        self.root.title("Fake News Dataset Explorer")
        self.root.geometry("1280x780")
        self.root.minsize(1000, 650)
        self.root.configure(bg=COLORS["page_bg"])

        self._build_shell()
        self.show_page("dashboard")

    # ------------------------------------------------------------------
    # SHELL: sidebar + header + content + status bar
    # ------------------------------------------------------------------
    def _build_shell(self):
        outer = tk.Frame(self.root, bg=COLORS["page_bg"])
        outer.pack(fill=BOTH, expand=True)
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(1, weight=1)

        self._build_sidebar(outer)

        right = tk.Frame(outer, bg=COLORS["page_bg"])
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self._build_header(right)

        self.content_host = tk.Frame(right, bg=COLORS["page_bg"])
        self.content_host.grid(row=1, column=0, sticky="nsew")
        self.content_host.grid_rowconfigure(0, weight=1)
        self.content_host.grid_columnconfigure(0, weight=1)

        self._build_status_bar(right)

    def _build_sidebar(self, parent):
        self.sidebar = tk.Frame(parent, bg=COLORS["sidebar_bg"], width=250)
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.grid_propagate(False)

        # --- logo / brand ---
        brand = tk.Frame(self.sidebar, bg=COLORS["sidebar_bg"])
        brand.pack(fill=X, pady=(22, 10), padx=18)
        brand_row = tk.Frame(brand, bg=COLORS["sidebar_bg"])
        brand_row.pack(fill=X)
        tk.Label(brand_row, text="📰", font=(FONT_FAMILY, 20), bg=COLORS["sidebar_bg"],
                  fg=COLORS["sidebar_text_active"]).pack(side=LEFT)
        self.brand_text = tk.Label(brand_row, text="  Fake News\n  Dataset Explorer",
                                    font=(FONT_FAMILY, 12, "bold"), bg=COLORS["sidebar_bg"],
                                    fg=COLORS["sidebar_text_active"], justify="left")
        self.brand_text.pack(side=LEFT)
        self.brand_subtitle = tk.Label(brand, text="Research Analytics Platform",
                                        font=(FONT_FAMILY, 8), bg=COLORS["sidebar_bg"],
                                        fg=COLORS["sidebar_text_muted"])
        self.brand_subtitle.pack(anchor="w", pady=(6, 0))

        sep = tk.Frame(self.sidebar, bg=COLORS["sidebar_hover"], height=1)
        sep.pack(fill=X, pady=(14, 6), padx=14)

        # --- nav sections ---
        self.nav_container = tk.Frame(self.sidebar, bg=COLORS["sidebar_bg"])
        self.nav_container.pack(fill=BOTH, expand=True)
        self._build_nav_items()

        # --- collapse toggle + footer ---
        toggle = tk.Label(self.sidebar, text="⟨⟨  Collapse", font=(FONT_FAMILY, 9),
                           bg=COLORS["sidebar_bg"], fg=COLORS["sidebar_text_muted"], cursor="hand2")
        toggle.pack(side=BOTTOM, fill=X, padx=18, pady=(4, 10), anchor="w")
        toggle.bind("<Button-1>", lambda e: self.toggle_sidebar())
        self.sidebar_toggle_label = toggle

        self.sidebar_footer = tk.Label(self.sidebar, text=f"{len(self.df):,} articles loaded",
                                        font=(FONT_FAMILY, 8), bg=COLORS["sidebar_bg"],
                                        fg=COLORS["sidebar_text_muted"])
        self.sidebar_footer.pack(side=BOTTOM, fill=X, padx=18, pady=(0, 4), anchor="w")

    def _build_nav_items(self):
        for section_title, items in self.SECTIONS:
            self._section_label = tk.Label(self.nav_container, text=section_title,
                                            font=(FONT_FAMILY, 8, "bold"), bg=COLORS["sidebar_bg"],
                                            fg=COLORS["sidebar_text_muted"])
            self._section_label.pack(anchor="w", padx=20, pady=(12, 4))
            for key, label, icon in items:
                self._create_nav_item(key, label, icon)

    def _create_nav_item(self, key, label, icon):
        row = tk.Frame(self.nav_container, bg=COLORS["sidebar_bg"], cursor="hand2")
        row.pack(fill=X, padx=10, pady=1)

        strip = tk.Frame(row, bg=COLORS["sidebar_bg"], width=4)
        strip.pack(side=LEFT, fill=Y)

        inner = tk.Frame(row, bg=COLORS["sidebar_bg"])
        inner.pack(side=LEFT, fill=X, expand=True, padx=(8, 4), pady=8)

        icon_lbl = tk.Label(inner, text=icon, font=(FONT_FAMILY, 12), bg=COLORS["sidebar_bg"],
                             fg=COLORS["sidebar_text"])
        icon_lbl.pack(side=LEFT)
        text_lbl = tk.Label(inner, text="  " + label, font=(FONT_FAMILY, 10),
                             bg=COLORS["sidebar_bg"], fg=COLORS["sidebar_text"])
        text_lbl.pack(side=LEFT)

        widgets = [row, inner, icon_lbl, text_lbl]
        for w in widgets:
            w.bind("<Button-1>", lambda e, k=key: self.show_page(k))
            w.bind("<Enter>", lambda e, k=key: self._nav_hover(k, True))
            w.bind("<Leave>", lambda e, k=key: self._nav_hover(k, False))

        if ToolTip is not None:
            try:
                ToolTip(icon_lbl, text=label)
            except Exception:
                pass

        self.nav_items[key] = {
            "row": row, "inner": inner, "icon": icon_lbl, "text": text_lbl,
            "strip": strip, "label": label,
        }

    def _nav_hover(self, key, entering):
        if key == self.current_page:
            return
        color = COLORS["sidebar_hover"] if entering else COLORS["sidebar_bg"]
        item = self.nav_items[key]
        for w in (item["row"], item["inner"], item["icon"], item["text"]):
            w.configure(bg=color)

    def toggle_sidebar(self):
        self.sidebar_collapsed = not self.sidebar_collapsed
        if self.sidebar_collapsed:
            self.sidebar.configure(width=68)
            self.brand_text.pack_forget()
            self.brand_subtitle.pack_forget()
            self.sidebar_footer.pack_forget()
            self.sidebar_toggle_label.configure(text="⟩⟩")
            for item in self.nav_items.values():
                item["text"].pack_forget()
        else:
            self.sidebar.configure(width=250)
            self.brand_text.pack(side=LEFT)
            self.brand_subtitle.pack(anchor="w", pady=(6, 0))
            self.sidebar_footer.pack(side=BOTTOM, fill=X, padx=18, pady=(0, 4), anchor="w")
            self.sidebar_toggle_label.configure(text="⟨⟨  Collapse")
            for item in self.nav_items.values():
                item["text"].pack(side=LEFT)

    def _build_header(self, parent):
        header = tk.Frame(parent, bg=COLORS["card_bg"], height=64)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(0, weight=1)

        left = tk.Frame(header, bg=COLORS["card_bg"])
        left.grid(row=0, column=0, sticky="w", padx=24, pady=10)
        self.header_title = tk.Label(left, text="", font=(FONT_FAMILY, 14, "bold"),
                                      bg=COLORS["card_bg"], fg=COLORS["text_primary"])
        self.header_title.pack(anchor="w")
        self.header_subtitle = tk.Label(left, text="", font=(FONT_FAMILY, 9),
                                         bg=COLORS["card_bg"], fg=COLORS["text_secondary"])
        self.header_subtitle.pack(anchor="w")

        right = tk.Frame(header, bg=COLORS["card_bg"])
        right.grid(row=0, column=1, sticky="e", padx=24)
        status = tk.Frame(right, bg=COLORS["real_soft"], padx=10, pady=5)
        status.pack(side=RIGHT)
        tk.Label(status, text="●", font=(FONT_FAMILY, 9), bg=COLORS["real_soft"],
                  fg=COLORS["real"]).pack(side=LEFT)
        tk.Label(status, text=f" Dataset Loaded  ·  {len(self.df):,} articles",
                  font=(FONT_FAMILY, 9, "bold"), bg=COLORS["real_soft"],
                  fg=COLORS["text_primary"]).pack(side=LEFT)

        sep = tk.Frame(parent, bg=COLORS["card_border"], height=1)
        sep.grid(row=0, column=0, sticky="sew")

    def _build_status_bar(self, parent):
        bar = tk.Frame(parent, bg="#E2E8F0", height=26)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_propagate(False)
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(bar, textvariable=self.status_var, font=(FONT_FAMILY, 8),
                  bg="#E2E8F0", fg=COLORS["text_secondary"]).pack(side=LEFT, padx=14)
        tk.Label(bar, text=f"{len(self.df):,} rows · {self.df['subject'].nunique()} subjects",
                  font=(FONT_FAMILY, 8), bg="#E2E8F0", fg=COLORS["text_secondary"]).pack(side=RIGHT, padx=14)

    def set_status(self, message):
        self.status_var.set(message)

    # ------------------------------------------------------------------
    # NAVIGATION / PAGE LIFECYCLE (lazy build + cache, so revisiting a
    # page never rebuilds its charts or leaks widgets)
    # ------------------------------------------------------------------
    def show_page(self, key):
        if key not in self.pages:
            self.set_status(f"Loading {self.PAGE_META[key][0]}...")
            self.root.update_idletasks()
            try:
                self.pages[key] = self._build_page(key)
            except Exception as e:
                log_exception(f"building page '{key}'", e)
                frame = tk.Frame(self.content_host, bg=COLORS["page_bg"])
                show_error_state(frame, "Something went wrong",
                                  "We couldn't build this page. The problem has been logged.")
                self.pages[key] = frame

        for frame in self.pages.values():
            frame.grid_forget()
        self.pages[key].grid(row=0, column=0, sticky="nsew")

        title, subtitle = self.PAGE_META[key]
        self.header_title.configure(text=title)
        self.header_subtitle.configure(text=subtitle)
        self.set_status("Ready")

        prev = self.current_page
        self.current_page = key
        for k, item in self.nav_items.items():
            active = (k == key)
            bg = COLORS["sidebar_active"] if active else COLORS["sidebar_bg"]
            fg = COLORS["sidebar_text_active"] if active else COLORS["sidebar_text"]
            for w in (item["row"], item["inner"], item["icon"], item["text"]):
                w.configure(bg=bg)
            item["icon"].configure(fg=fg)
            item["text"].configure(fg=fg)
            item["strip"].configure(bg=COLORS["accent"] if active else COLORS["sidebar_bg"])

    def _build_page(self, key):
        builder = getattr(self, f"_page_{key}")
        return builder()

    def _scrollable_page(self):
        """Standard scrollable page container so content never gets cut
        off at smaller window sizes."""
        page = tk.Frame(self.content_host, bg=COLORS["page_bg"])
        canvas = tk.Canvas(page, bg=COLORS["page_bg"], highlightthickness=0)
        vsb = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        vsb.pack(side=RIGHT, fill=Y)

        inner = tk.Frame(canvas, bg=COLORS["page_bg"], padx=28, pady=22)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_configure(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(win, width=canvas.winfo_width())
        inner.bind("<Configure>", on_configure)
        canvas.bind("<Configure>", on_configure)

        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all_local = lambda: None
        inner.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", on_mousewheel))
        inner.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        return page, inner

    def _embed_figure(self, fig, parent):
        for widget in parent.winfo_children():
            widget.destroy()
        # Pin the container to the figure's real pixel size. Without this,
        # a chart nested inside the scrollable page can be squeezed shorter
        # than it was drawn (especially with Windows display scaling),
        # which crams horizontal bar labels on top of each other.
        width_px = int(round(fig.get_size_inches()[0] * fig.dpi))
        height_px = int(round(fig.get_size_inches()[1] * fig.dpi))
        parent.configure(width=width_px, height=height_px)
        parent.pack_propagate(False)
        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=BOTH, expand=True)
        plt.close(fig)

    # ------------------------------------------------------------------
    # DASHBOARD
    # ------------------------------------------------------------------
    def _page_dashboard(self):
        page, body = self._scrollable_page()

        fake_n = int((self.df["label"] == "Fake").sum())
        real_n = int((self.df["label"] == "Real").sum())
        total = len(self.df)
        avg_len = self.df["text_length"].mean()
        retention = self.meta.get("retention", 100.0)

        kpi_row = tk.Frame(body, bg=COLORS["page_bg"])
        kpi_row.pack(fill=X, pady=(0, 18))
        for i in range(5):
            kpi_row.grid_columnconfigure(i, weight=1, uniform="kpi")

        create_kpi_card(kpi_row, "📄", f"{total:,}", "Total Articles",
                         "Articles in dataset", COLORS["accent"]).grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        create_kpi_card(kpi_row, "🔴", f"{fake_n:,}", "Fake News",
                         f"{fake_n/total*100:.1f}% of dataset", COLORS["fake"]).grid(row=0, column=1, sticky="nsew", padx=5)
        create_kpi_card(kpi_row, "🟢", f"{real_n:,}", "Real News",
                         f"{real_n/total*100:.1f}% of dataset", COLORS["real"]).grid(row=0, column=2, sticky="nsew", padx=5)
        create_kpi_card(kpi_row, "📏", f"{avg_len:.0f} words", "Average Article Length",
                         "Mean article size", COLORS["warning"]).grid(row=0, column=3, sticky="nsew", padx=5)
        create_kpi_card(kpi_row, "✅", f"{retention:.1f}%", "Dataset Retention",
                         "Rows kept after cleaning", COLORS["success"]).grid(row=0, column=4, sticky="nsew", padx=(10, 0))

        chart_row = tk.Frame(body, bg=COLORS["page_bg"])
        chart_row.pack(fill=BOTH, expand=True)
        chart_row.grid_columnconfigure(0, weight=1, uniform="charts")
        chart_row.grid_columnconfigure(1, weight=1, uniform="charts")

        donut_card, donut_area = create_chart_container(chart_row, "News Classification")
        donut_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 16))
        counts = self.df["label"].value_counts()
        fig1, ax1 = plt.subplots(figsize=(4.6, 4.0))
        wedges, _ = ax1.pie(counts.values, colors=[label_color(l) for l in counts.index],
                             startangle=90, wedgeprops=dict(width=0.42, edgecolor=COLORS["card_bg"]))
        fake_pct = fake_n / total * 100
        ax1.text(0, 0.08, f"{fake_pct:.1f}%", ha="center", va="center",
                  fontsize=19, fontweight="bold", color=COLORS["fake"])
        ax1.text(0, -0.18, "Fake", ha="center", va="center", fontsize=10, color=COLORS["text_secondary"])
        ax1.set_aspect("equal")
        fig1.patch.set_facecolor(COLORS["card_bg"])
        legend_labels = [f"{l}  ({counts[l]:,})" for l in counts.index]
        ax1.legend(wedges, legend_labels, loc="upper center", bbox_to_anchor=(0.5, -0.02),
                   ncol=2, frameon=False, fontsize=9)
        fig1.tight_layout()
        self._embed_figure(fig1, donut_area)

        hist_card, hist_area = create_chart_container(chart_row, "Article Length Distribution")
        hist_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=(0, 16))
        fig2, ax2 = plt.subplots(figsize=(4.6, 4.0))
        ax2.hist(self.df[self.df["label"] == "Fake"]["text_length"], bins=40,
                  alpha=0.65, label="Fake", color=COLORS["fake"])
        ax2.hist(self.df[self.df["label"] == "Real"]["text_length"], bins=40,
                  alpha=0.65, label="Real", color=COLORS["real"])
        style_axes(ax2, fig2, xlabel="Word Count", ylabel="Articles")
        ax2.legend(frameon=False, fontsize=9)
        fig2.tight_layout()
        self._embed_figure(fig2, hist_area)

        insight_card, insight_area = create_section_card(body, "Dataset Insights")
        insight_card.pack(fill=X)
        top_subject = self.df["subject"].value_counts().idxmax()
        top_subject_pct = self.df["subject"].value_counts(normalize=True).max() * 100
        insights = [
            f"•  Real news represents {real_n/total*100:.1f}% of the dataset ({real_n:,} of {total:,} articles).",
            f"•  The average article is {avg_len:.0f} words long.",
            f"•  The most represented subject is \"{top_subject}\" ({top_subject_pct:.1f}% of all articles).",
            f"•  {self.meta.get('dupes_removed', 0):,} duplicate rows and {self.meta.get('missing_removed', 0):,} "
            f"rows with missing text were removed during cleaning ({retention:.1f}% retention).",
        ]
        for line in insights:
            tk.Label(insight_area, text=line, font=(FONT_FAMILY, 10), bg=COLORS["card_bg"],
                      fg=COLORS["text_primary"], anchor="w", justify="left").pack(anchor="w", pady=2)

        return page

    # ------------------------------------------------------------------
    # CATEGORY DISTRIBUTION
    # ------------------------------------------------------------------
    def _page_category(self):
        page, body = self._scrollable_page()

        counts = self.df["label"].value_counts()
        pct = (counts / counts.sum() * 100)
        total = len(self.df)

        kpi_row = tk.Frame(body, bg=COLORS["page_bg"])
        kpi_row.pack(fill=X, pady=(0, 18))
        for i in range(3):
            kpi_row.grid_columnconfigure(i, weight=1, uniform="k")
        create_kpi_card(kpi_row, "📄", f"{total:,}", "Total Articles", None, COLORS["accent"]).grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        create_kpi_card(kpi_row, "🔴", f"{counts.get('Fake', 0):,}", "Fake Articles",
                         f"{pct.get('Fake', 0):.1f}%", COLORS["fake"]).grid(row=0, column=1, sticky="nsew", padx=8)
        create_kpi_card(kpi_row, "🟢", f"{counts.get('Real', 0):,}", "Real Articles",
                         f"{pct.get('Real', 0):.1f}%", COLORS["real"]).grid(row=0, column=2, sticky="nsew", padx=(8, 0))

        chart_card, chart_area = create_chart_container(body, "Fake vs Real News Distribution")
        chart_card.pack(fill=BOTH, expand=True, pady=(0, 16))
        fig, ax = plt.subplots(figsize=(6.4, 4.6))
        wedges, texts, autotexts = ax.pie(
            counts.values, labels=counts.index, autopct='%1.1f%%',
            colors=[label_color(l) for l in counts.index], startangle=90,
            wedgeprops=dict(edgecolor=COLORS["card_bg"], linewidth=1.5),
            textprops=dict(fontsize=10, color=COLORS["text_primary"]))
        for t in autotexts:
            t.set_color("white")
            t.set_fontweight("bold")
        ax.set_aspect("equal")
        fig.tight_layout()
        self._embed_figure(fig, chart_area)

        diff = abs(pct.get("Fake", 0) - pct.get("Real", 0))
        insight_card, insight_area = create_section_card(body, "Insight")
        insight_card.pack(fill=X)
        balance = "very close to balanced" if diff < 2 else f"skewed by {diff:.1f} percentage points"
        tk.Label(insight_area,
                  text=f"•  The dataset is {balance} between Fake and Real articles.",
                  font=(FONT_FAMILY, 10), bg=COLORS["card_bg"], fg=COLORS["text_primary"]).pack(anchor="w")

        return page

    # ------------------------------------------------------------------
    # TEXT LENGTH
    # ------------------------------------------------------------------
    def _page_length(self):
        page, body = self._scrollable_page()

        fake_len = self.df[self.df["label"] == "Fake"]["text_length"]
        real_len = self.df[self.df["label"] == "Real"]["text_length"]

        kpi_row = tk.Frame(body, bg=COLORS["page_bg"])
        kpi_row.pack(fill=X, pady=(0, 18))
        for i in range(4):
            kpi_row.grid_columnconfigure(i, weight=1, uniform="k")
        create_kpi_card(kpi_row, "🔴", f"{fake_len.mean():.0f}", "Fake Average (words)", None, COLORS["fake"]).grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        create_kpi_card(kpi_row, "🟢", f"{real_len.mean():.0f}", "Real Average (words)", None, COLORS["real"]).grid(row=0, column=1, sticky="nsew", padx=8)
        create_kpi_card(kpi_row, "🔴", f"{fake_len.median():.0f}", "Fake Median (words)", None, COLORS["fake"]).grid(row=0, column=2, sticky="nsew", padx=8)
        create_kpi_card(kpi_row, "🟢", f"{real_len.median():.0f}", "Real Median (words)", None, COLORS["real"]).grid(row=0, column=3, sticky="nsew", padx=(8, 0))

        chart_card, chart_area = create_chart_container(body, "Text Length Distribution")
        chart_card.pack(fill=BOTH, expand=True, pady=(0, 16))
        fig, ax = plt.subplots(figsize=(9, 4.2))
        ax.hist(fake_len, alpha=0.65, label="Fake", bins=50, color=COLORS["fake"])
        ax.hist(real_len, alpha=0.65, label="Real", bins=50, color=COLORS["real"])
        style_axes(ax, fig, xlabel="Word Count", ylabel="Number of Articles")
        ax.legend(frameon=False, fontsize=9)
        fig.tight_layout()
        self._embed_figure(fig, chart_area)

        table_card, table_area = create_section_card(body, "Statistical Summary")
        table_card.pack(fill=X)
        rows = [
            ("Mean", fake_len.mean(), real_len.mean()),
            ("Median", fake_len.median(), real_len.median()),
            ("Std. Dev.", np.std(fake_len), np.std(real_len)),
            ("Minimum", fake_len.min(), real_len.min()),
            ("Maximum", fake_len.max(), real_len.max()),
        ]
        header = tk.Frame(table_area, bg=COLORS["card_bg"])
        header.pack(fill=X)
        for i, text in enumerate(("Metric", "Fake", "Real")):
            tk.Label(header, text=text, font=(FONT_FAMILY, 10, "bold"), bg=COLORS["card_bg"],
                      fg=COLORS["text_primary"], width=16, anchor="w").grid(row=0, column=i, sticky="w", pady=(0, 6))
        for r, (metric, fv, rv) in enumerate(rows, start=1):
            row_bg = "#F8FAFC" if r % 2 == 0 else COLORS["card_bg"]
            row_frame = tk.Frame(table_area, bg=row_bg)
            row_frame.pack(fill=X)
            tk.Label(row_frame, text=metric, font=(FONT_FAMILY, 10), bg=row_bg,
                      fg=COLORS["text_primary"], width=16, anchor="w", pady=4).grid(row=0, column=0, sticky="w")
            tk.Label(row_frame, text=f"{fv:.1f}", font=(FONT_FAMILY, 10), bg=row_bg,
                      fg=COLORS["fake"], width=16, anchor="w").grid(row=0, column=1, sticky="w")
            tk.Label(row_frame, text=f"{rv:.1f}", font=(FONT_FAMILY, 10), bg=row_bg,
                      fg=COLORS["real"], width=16, anchor="w").grid(row=0, column=2, sticky="w")

        return page

    # ------------------------------------------------------------------
    # SOURCE COMPARISON
    # ------------------------------------------------------------------
    def _page_source(self):
        page, body = self._scrollable_page()

        pivot = pd.pivot_table(self.df, index="subject", columns="label",
                                values="title", aggfunc="count", fill_value=0)
        for col in ("Fake", "Real"):
            if col not in pivot.columns:
                pivot[col] = 0
        pivot["Total"] = pivot["Fake"] + pivot["Real"]
        pivot = pivot.sort_values("Total", ascending=True)
        pivot["Diff"] = (pivot["Fake"] - pivot["Real"]).abs()

        n_subjects = len(pivot)
        most_represented = pivot["Total"].idxmax()
        largest_diff_subject = pivot["Diff"].idxmax()

        kpi_row = tk.Frame(body, bg=COLORS["page_bg"])
        kpi_row.pack(fill=X, pady=(0, 18))
        for i in range(3):
            kpi_row.grid_columnconfigure(i, weight=1, uniform="k")
        create_kpi_card(kpi_row, "🗂", f"{n_subjects}", "Subjects", None, COLORS["accent"]).grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        create_kpi_card(kpi_row, "🏆", most_represented, "Most Represented Subject",
                         f"{int(pivot.loc[most_represented, 'Total']):,} articles", COLORS["warning"]).grid(row=0, column=1, sticky="nsew", padx=8)
        create_kpi_card(kpi_row, "⚖️", largest_diff_subject, "Largest Fake/Real Gap",
                         f"{int(pivot.loc[largest_diff_subject, 'Diff']):,} article difference", COLORS["neutral"]).grid(row=0, column=2, sticky="nsew", padx=(8, 0))

        chart_card, chart_area = create_chart_container(body, "Subject Distribution by Label")
        chart_card.pack(fill=BOTH, expand=True)
        fig_height = max(4.2, n_subjects * 0.42)
        fig, ax = plt.subplots(figsize=(9, fig_height))
        pivot[["Fake", "Real"]].plot(kind="barh", stacked=True, ax=ax,
                                      color=[COLORS["fake"], COLORS["real"]])
        style_axes(ax, fig, xlabel="Article Count")
        ax.set_ylabel("")
        ax.legend(frameon=False, fontsize=9)
        fig.tight_layout()
        self._embed_figure(fig, chart_area)

        return page

    # ------------------------------------------------------------------
    # COMMON WORDS
    # ------------------------------------------------------------------
    def _page_words(self):
        page, body = self._scrollable_page()

        controls_card, controls = create_section_card(body, None)
        controls_card.pack(fill=X, pady=(0, 16))
        row = tk.Frame(controls, bg=COLORS["card_bg"])
        row.pack(fill=X)

        tk.Label(row, text="News Type", font=(FONT_FAMILY, 9, "bold"), bg=COLORS["card_bg"],
                  fg=COLORS["text_secondary"]).grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.words_type_var = tk.StringVar(value="All")
        type_combo = ttk.Combobox(row, textvariable=self.words_type_var, values=["All", "Fake", "Real"],
                                   state="readonly", width=10)
        type_combo.grid(row=0, column=1, padx=(0, 20))

        tk.Label(row, text="Top Words", font=(FONT_FAMILY, 9, "bold"), bg=COLORS["card_bg"],
                  fg=COLORS["text_secondary"]).grid(row=0, column=2, sticky="w", padx=(0, 6))
        self.words_topn_var = tk.StringVar(value="15")
        n_combo = ttk.Combobox(row, textvariable=self.words_topn_var, values=["10", "15", "20", "30", "50"],
                                state="readonly", width=6)
        n_combo.grid(row=0, column=3, padx=(0, 20))

        analyze_btn = tb.Button(row, text="Analyze", command=self.refresh_words, bootstyle="primary")
        analyze_btn.grid(row=0, column=4)
        self.words_analyze_btn = analyze_btn
        type_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_words())
        n_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_words())

        tk.Label(controls, text="Words are lowercased, stripped of punctuation, filtered against a "
                                  "stopword list, and must be longer than 2 characters before being counted.",
                  font=(FONT_FAMILY, 8), bg=COLORS["card_bg"], fg=COLORS["text_secondary"],
                  wraplength=900, justify="left").pack(anchor="w", pady=(10, 0))

        chart_card, chart_area = create_chart_container(body, "Most Frequent Words")
        chart_card.pack(fill=BOTH, expand=True)
        self.words_chart_area = chart_area
        self.words_status_label = tk.Label(chart_area, text="", font=(FONT_FAMILY, 9),
                                            bg=COLORS["card_bg"], fg=COLORS["text_secondary"])

        self.refresh_words()
        return page

    def refresh_words(self):
        news_type = self.words_type_var.get()
        try:
            top_n = int(self.words_topn_var.get())
        except ValueError:
            top_n = 15

        for w in self.words_chart_area.winfo_children():
            w.destroy()
        tk.Label(self.words_chart_area, text="Calculating word frequencies...", font=(FONT_FAMILY, 10),
                  bg=COLORS["card_bg"], fg=COLORS["text_secondary"]).pack(pady=40)
        self.words_analyze_btn.configure(state="disabled")
        self.set_status("Calculating word frequencies...")

        subset = self.df if news_type == "All" else self.df[self.df["label"] == news_type]
        color = COLORS["accent"] if news_type == "All" else label_color(news_type)

        def work():
            return get_common_words(subset["text"], n=top_n)

        def done(top_words):
            self.words_analyze_btn.configure(state="normal")
            self.set_status("Ready")
            for w in self.words_chart_area.winfo_children():
                w.destroy()
            if not top_words:
                show_empty_state(self.words_chart_area, "🔤", "No words found",
                                  "There isn't enough text data to compute word frequencies for this selection.")
                return
            words, counts = zip(*top_words)
            fig, ax = plt.subplots(figsize=(9, max(3.5, len(words) * 0.4)))
            bars = ax.barh(words, counts, color=color)
            ax.invert_yaxis()
            style_axes(ax, fig, title=f"Top {len(words)} Words - {news_type} News", xlabel="Frequency")
            for bar in bars:
                width = bar.get_width()
                ax.text(width + max(counts) * 0.01, bar.get_y() + bar.get_height() / 2,
                        f"{int(width):,}", va="center", fontsize=8, color=COLORS["text_secondary"])
            fig.tight_layout()
            self._embed_figure(fig, self.words_chart_area)

        def error(e):
            self.words_analyze_btn.configure(state="normal")
            self.set_status("Ready")
            for w in self.words_chart_area.winfo_children():
                w.destroy()
            show_error_state(self.words_chart_area, "Couldn't calculate word frequencies",
                              "Something went wrong analyzing the text. The problem has been logged.")

        run_in_background(self.root, work, done, error)

    # ------------------------------------------------------------------
    # TREND ANALYSIS
    # ------------------------------------------------------------------
    def _page_trend(self):
        page, body = self._scrollable_page()

        trend_df = self.df.dropna(subset=["date_parsed"]).copy()
        if trend_df.empty:
            card, area = create_section_card(body, None)
            card.pack(fill=BOTH, expand=True)
            show_empty_state(area, "📅", "No Valid Date Data",
                              "There are not enough valid publication dates to generate a meaningful monthly trend.")
            return page

        trend_df["month_year"] = trend_df["date_parsed"].dt.to_period("M").astype(str)
        monthly = trend_df.groupby(["month_year", "label"]).size().unstack(fill_value=0)
        for col in ("Fake", "Real"):
            if col not in monthly.columns:
                monthly[col] = 0
        monthly["Total"] = monthly["Fake"] + monthly["Real"]

        peak_fake_month = monthly["Fake"].idxmax()
        peak_real_month = monthly["Real"].idxmax()
        peak_total_month = monthly["Total"].idxmax()

        kpi_row = tk.Frame(body, bg=COLORS["page_bg"])
        kpi_row.pack(fill=X, pady=(0, 18))
        for i in range(3):
            kpi_row.grid_columnconfigure(i, weight=1, uniform="k")
        create_kpi_card(kpi_row, "🔴", peak_fake_month, "Peak Fake Month",
                         f"{int(monthly['Fake'].max()):,} articles", COLORS["fake"]).grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        create_kpi_card(kpi_row, "🟢", peak_real_month, "Peak Real Month",
                         f"{int(monthly['Real'].max()):,} articles", COLORS["real"]).grid(row=0, column=1, sticky="nsew", padx=8)
        create_kpi_card(kpi_row, "📈", peak_total_month, "Highest Volume Month",
                         f"{int(monthly['Total'].max()):,} articles", COLORS["accent"]).grid(row=0, column=2, sticky="nsew", padx=(8, 0))

        note = ""
        valid_dates = self.meta.get("valid_dates", len(trend_df))
        if valid_dates < len(self.df):
            note = f"  ({len(self.df) - valid_dates:,} of {len(self.df):,} rows had unparseable dates and are excluded.)"

        chart_card, chart_area = create_chart_container(body, "Monthly Trend: Fake vs Real News" + note)
        chart_card.pack(fill=BOTH, expand=True)
        fig, ax = plt.subplots(figsize=(9.5, 4.6))
        ax.plot(monthly.index, monthly["Fake"], marker="o", markersize=3, color=COLORS["fake"], label="Fake News")
        ax.plot(monthly.index, monthly["Real"], marker="o", markersize=3, color=COLORS["real"], label="Real News")
        ax.plot(monthly.index, monthly["Total"], marker="o", markersize=3, color=COLORS["neutral"],
                linestyle="--", linewidth=1, label="Total Articles")
        style_axes(ax, fig, xlabel="Month", ylabel="Number of Articles")
        ax.legend(frameon=False, fontsize=9)
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right", fontsize=8)
        fig.tight_layout()
        self._embed_figure(fig, chart_area)

        return page

    # ------------------------------------------------------------------
    # TOP / BOTTOM RECORDS
    # ------------------------------------------------------------------
    def _page_topbottom(self):
        page, body = self._scrollable_page()

        row = tk.Frame(body, bg=COLORS["page_bg"])
        row.pack(fill=BOTH, expand=True)
        row.grid_columnconfigure(0, weight=1, uniform="tb")
        row.grid_columnconfigure(1, weight=1, uniform="tb")
        row.grid_rowconfigure(0, weight=1)

        longest = self.df.nlargest(10, "text_length")
        shortest = self.df.nsmallest(10, "text_length")

        long_card, long_area = create_section_card(row, "Longest Articles")
        long_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self._build_records_table(long_area, longest)

        short_card, short_area = create_section_card(row, "Shortest Articles")
        short_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self._build_records_table(short_area, shortest)

        tip = tk.Label(body, text="Tip: double-click any row to open the full article.",
                        font=(FONT_FAMILY, 8), bg=COLORS["page_bg"], fg=COLORS["text_secondary"])
        tip.pack(anchor="w", pady=(10, 0))

        return page

    def _build_records_table(self, parent, dataframe):
        columns = ("rank", "title", "label", "subject", "words")
        headings = ("#", "Title", "Label", "Subject", "Words")
        widths = (32, 280, 60, 130, 70)
        wrapper, tree = create_table(parent, columns, headings, widths, height=14)
        wrapper.pack(fill=BOTH, expand=True)

        def to_values(row):
            return (row["_rank"], row["title"][:80], row["label"], row["subject"], f"{row['text_length']:,}")

        rows = []
        for i, (_, r) in enumerate(dataframe.iterrows(), start=1):
            r = r.copy()
            r["_rank"] = i
            rows.append(r)
        populate_table(tree, rows, to_values)
        tree.bind("<Double-1>", lambda e, t=tree: self._on_row_double_click(t))

    def _on_row_double_click(self, tree):
        sel = tree.selection()
        if not sel:
            return
        row = tree.row_data.get(sel[0])
        if row is not None:
            self.open_article_detail(row)

    # ------------------------------------------------------------------
    # SEARCH
    # ------------------------------------------------------------------
    def _page_search(self):
        page, body = self._scrollable_page()

        filter_card, filters = create_section_card(body, "Search Filters")
        filter_card.pack(fill=X, pady=(0, 16))

        row1 = tk.Frame(filters, bg=COLORS["card_bg"])
        row1.pack(fill=X, pady=(0, 10))
        tk.Label(row1, text="Search", font=(FONT_FAMILY, 9, "bold"), bg=COLORS["card_bg"],
                  fg=COLORS["text_secondary"]).pack(side=LEFT, padx=(0, 6))
        self.search_term = tk.StringVar()
        entry = ttk.Entry(row1, textvariable=self.search_term, width=42)
        entry.pack(side=LEFT, padx=(0, 20))
        entry.bind("<Return>", lambda e: self.run_search())

        row2 = tk.Frame(filters, bg=COLORS["card_bg"])
        row2.pack(fill=X)

        tk.Label(row2, text="Label", font=(FONT_FAMILY, 9, "bold"), bg=COLORS["card_bg"],
                  fg=COLORS["text_secondary"]).grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.search_label_filter = tk.StringVar(value="All")
        ttk.Combobox(row2, textvariable=self.search_label_filter, values=["All", "Fake", "Real"],
                     state="readonly", width=8).grid(row=0, column=1, padx=(0, 20))

        tk.Label(row2, text="Subject", font=(FONT_FAMILY, 9, "bold"), bg=COLORS["card_bg"],
                  fg=COLORS["text_secondary"]).grid(row=0, column=2, sticky="w", padx=(0, 6))
        subjects = ["All"] + sorted(self.df["subject"].unique().tolist())
        self.search_subject_filter = tk.StringVar(value="All")
        ttk.Combobox(row2, textvariable=self.search_subject_filter, values=subjects,
                     state="readonly", width=16).grid(row=0, column=3, padx=(0, 20))

        tk.Label(row2, text="Min Words", font=(FONT_FAMILY, 9, "bold"), bg=COLORS["card_bg"],
                  fg=COLORS["text_secondary"]).grid(row=0, column=4, sticky="w", padx=(0, 6))
        self.search_min_words = tk.StringVar()
        ttk.Entry(row2, textvariable=self.search_min_words, width=8).grid(row=0, column=5, padx=(0, 20))

        tk.Label(row2, text="Max Words", font=(FONT_FAMILY, 9, "bold"), bg=COLORS["card_bg"],
                  fg=COLORS["text_secondary"]).grid(row=0, column=6, sticky="w", padx=(0, 6))
        self.search_max_words = tk.StringVar()
        ttk.Entry(row2, textvariable=self.search_max_words, width=8).grid(row=0, column=7, padx=(0, 20))

        btn_row = tk.Frame(filters, bg=COLORS["card_bg"])
        btn_row.pack(fill=X, pady=(14, 0))
        self.search_btn = tb.Button(btn_row, text="Search", bootstyle="primary", command=self.run_search)
        self.search_btn.pack(side=LEFT, padx=(0, 8))
        tb.Button(btn_row, text="Clear", bootstyle="secondary-outline", command=self.clear_search).pack(side=LEFT)

        self.search_result_label = tk.Label(body, text="Enter a keyword and press Search, or adjust filters and search with an empty keyword to browse.",
                                             font=(FONT_FAMILY, 10), bg=COLORS["page_bg"], fg=COLORS["text_secondary"])
        self.search_result_label.pack(anchor="w", pady=(0, 8))

        results_card, results_area = create_section_card(body, None)
        results_card.pack(fill=BOTH, expand=True)
        columns = ("title", "label", "subject", "date", "words")
        headings = ("Title", "Label", "Subject", "Date", "Word Count")
        widths = (360, 60, 130, 100, 90)
        wrapper, self.search_tree = create_table(results_area, columns, headings, widths, height=16)
        wrapper.pack(fill=BOTH, expand=True)
        self.search_tree.bind("<Double-1>", lambda e: self._on_row_double_click(self.search_tree))

        tip = tk.Label(body, text="Tip: double-click any row to open the full article.",
                        font=(FONT_FAMILY, 8), bg=COLORS["page_bg"], fg=COLORS["text_secondary"])
        tip.pack(anchor="w", pady=(8, 0))

        return page

    def clear_search(self):
        self.search_term.set("")
        self.search_label_filter.set("All")
        self.search_subject_filter.set("All")
        self.search_min_words.set("")
        self.search_max_words.set("")
        for iid in self.search_tree.get_children():
            self.search_tree.delete(iid)
        self.search_tree.row_data = {}
        self.search_result_label.configure(text="Enter a keyword and press Search, or adjust filters and search with an empty keyword to browse.")

    def run_search(self):
        term = self.search_term.get().strip()
        label_filter = self.search_label_filter.get()
        subject_filter = self.search_subject_filter.get()

        def parse_bound(value):
            value = value.strip()
            if not value:
                return None
            try:
                return int(value)
            except ValueError:
                return None

        min_words = parse_bound(self.search_min_words.get())
        max_words = parse_bound(self.search_max_words.get())

        self.search_btn.configure(state="disabled")
        self.search_result_label.configure(text="Searching...")
        self.set_status("Searching articles...")

        def work():
            subset = self.df
            if label_filter != "All":
                subset = subset[subset["label"] == label_filter]
            if subject_filter != "All":
                subset = subset[subset["subject"] == subject_filter]
            if min_words is not None:
                subset = subset[subset["text_length"] >= min_words]
            if max_words is not None:
                subset = subset[subset["text_length"] <= max_words]
            if term:
                mask = subset["title"].str.contains(term, case=False, na=False, regex=False) | \
                       subset["text"].str.contains(term, case=False, na=False, regex=False)
                subset = subset[mask]
            return subset

        def done(results):
            self.search_btn.configure(state="normal")
            self.set_status("Ready")
            total_matches = len(results)
            shown = results.head(200)
            self.search_result_label.configure(
                text=f"{total_matches:,} Matching Articles" + (" (showing first 200)" if total_matches > 200 else "")
            )

            def to_values(row):
                date_str = row["date_parsed"].strftime("%Y-%m-%d") if pd.notna(row["date_parsed"]) else "Unknown"
                return (row["title"][:90], row["label"], row["subject"], date_str, f"{row['text_length']:,}")

            populate_table(self.search_tree, [r for _, r in shown.iterrows()], to_values)

        def error(e):
            self.search_btn.configure(state="normal")
            self.set_status("Ready")
            self.search_result_label.configure(text="Search failed. Please try again.")

        run_in_background(self.root, work, done, error)

    # ------------------------------------------------------------------
    # ARTICLE DETAIL VIEW
    # ------------------------------------------------------------------
    def open_article_detail(self, row):
        win = tk.Toplevel(self.root)
        win.title("Article Details")
        win.geometry("720x600")
        win.configure(bg=COLORS["card_bg"])
        win.transient(self.root)

        header = tk.Frame(win, bg=COLORS["card_bg"], padx=24, pady=18)
        header.pack(fill=X)
        tk.Label(header, text=row["title"], font=(FONT_FAMILY, 15, "bold"), bg=COLORS["card_bg"],
                  fg=COLORS["text_primary"], wraplength=660, justify="left").pack(anchor="w")

        meta_row = tk.Frame(header, bg=COLORS["card_bg"])
        meta_row.pack(anchor="w", pady=(12, 0))
        badge = create_badge(meta_row, ("🔴 Fake" if row["label"] == "Fake" else "🟢 Real"),
                              "fake" if row["label"] == "Fake" else "real")
        badge.pack(side=LEFT, padx=(0, 10))
        date_str = row["date_parsed"].strftime("%Y-%m-%d") if pd.notna(row.get("date_parsed")) else "Unknown date"
        tk.Label(meta_row, text=f"Subject: {row['subject']}   ·   {date_str}   ·   {row['text_length']:,} words",
                  font=(FONT_FAMILY, 9), bg=COLORS["card_bg"], fg=COLORS["text_secondary"]).pack(side=LEFT)

        sep = tk.Frame(win, bg=COLORS["card_border"], height=1)
        sep.pack(fill=X)

        body = tk.Frame(win, bg=COLORS["card_bg"], padx=24, pady=16)
        body.pack(fill=BOTH, expand=True)
        tk.Label(body, text="Article Content", font=(FONT_FAMILY, 10, "bold"), bg=COLORS["card_bg"],
                  fg=COLORS["text_primary"]).pack(anchor="w", pady=(0, 8))

        text_frame = tk.Frame(body, bg=COLORS["card_bg"])
        text_frame.pack(fill=BOTH, expand=True)
        text_widget = tk.Text(text_frame, wrap="word", font=(FONT_FAMILY, 10), bg="#F8FAFC",
                               fg=COLORS["text_primary"], relief="flat", padx=12, pady=12)
        vsb = ttk.Scrollbar(text_frame, orient="vertical", command=text_widget.yview)
        text_widget.configure(yscrollcommand=vsb.set)
        text_widget.pack(side=LEFT, fill=BOTH, expand=True)
        vsb.pack(side=RIGHT, fill=Y)
        text_widget.insert("1.0", str(row["text"]))
        text_widget.configure(state="disabled")

        footer = tk.Frame(win, bg=COLORS["card_bg"], padx=24, pady=14)
        footer.pack(fill=X)

        def copy_article():
            self.root.clipboard_clear()
            self.root.clipboard_append(str(row["text"]))
            show_success_toast(win, "Article copied to clipboard")

        tb.Button(footer, text="Copy Article", bootstyle="secondary", command=copy_article).pack(side=LEFT)
        tb.Button(footer, text="Close", bootstyle="primary", command=win.destroy).pack(side=RIGHT)

    # ------------------------------------------------------------------
    # EXPORT
    # ------------------------------------------------------------------
    def _page_export(self):
        page, body = self._scrollable_page()

        card, content = create_section_card(body, None)
        card.pack(fill=X)

        tk.Label(content, text="Dataset Ready", font=(FONT_FAMILY, 14, "bold"), bg=COLORS["card_bg"],
                  fg=COLORS["text_primary"]).pack(anchor="w")
        tk.Label(content, text=f"{len(self.df):,} records", font=(FONT_FAMILY, 11),
                  bg=COLORS["card_bg"], fg=COLORS["accent"]).pack(anchor="w", pady=(2, 16))

        checklist = [
            f"✓  Duplicate handling — {self.meta.get('dupes_removed', 0):,} duplicate rows removed",
            f"✓  Missing-text handling — {self.meta.get('missing_removed', 0):,} rows with empty text removed",
            "✓  Label assignment — every row tagged Fake or Real",
            "✓  Text-length calculation — word count computed per article",
            f"✓  Date parsing — {self.meta.get('valid_dates', 0):,} of {len(self.df):,} dates parsed successfully",
        ]
        for line in checklist:
            tk.Label(content, text=line, font=(FONT_FAMILY, 10), bg=COLORS["card_bg"],
                      fg=COLORS["text_primary"], anchor="w").pack(anchor="w", pady=3)

        self.export_btn = tb.Button(content, text="Export CSV", bootstyle="success",
                                      command=self.export_data)
        self.export_btn.pack(anchor="w", pady=(18, 6))
        self.export_status = tk.Label(content, text="", font=(FONT_FAMILY, 9), bg=COLORS["card_bg"],
                                       fg=COLORS["text_secondary"])
        self.export_status.pack(anchor="w")

        return page

    def export_data(self):
        path = filedialog.asksaveasfilename(
            title="Export cleaned dataset",
            defaultextension=".csv",
            initialfile="cleaned_news_data.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return

        self.export_btn.configure(state="disabled")
        self.export_status.configure(text="Exporting dataset...")
        self.set_status("Exporting dataset...")

        def work():
            self.df.to_csv(path, index=False)
            return path

        def done(saved_path):
            self.export_btn.configure(state="normal")
            self.export_status.configure(text=f"✓ Exported to {saved_path}")
            self.set_status("Ready")
            show_success_toast(self.root, "Your cleaned dataset has been saved successfully.")

        def error(e):
            self.export_btn.configure(state="normal")
            self.export_status.configure(text="Export failed.")
            self.set_status("Ready")
            messagebox.showerror("Export failed",
                                  f"We couldn't save the file. It may be open in another program.\n\n{e}")

        run_in_background(self.root, work, done, error)


# ============================================================================
# 6. STARTUP: splash screen loads data on a background thread
# ============================================================================

def run_splash_then_launch():
    root = tb.Window(themename="flatly")
    root.title("Fake News Dataset Explorer")
    root.geometry("460x220")
    root.resizable(False, False)
    root.configure(bg=COLORS["card_bg"])

    wrap = tk.Frame(root, bg=COLORS["card_bg"])
    wrap.pack(fill=BOTH, expand=True, padx=30, pady=30)
    tk.Label(wrap, text="📰", font=(FONT_FAMILY, 30), bg=COLORS["card_bg"]).pack(pady=(4, 6))
    tk.Label(wrap, text="Fake News Dataset Explorer", font=(FONT_FAMILY, 14, "bold"),
              bg=COLORS["card_bg"], fg=COLORS["text_primary"]).pack()
    status_var = tk.StringVar(value="Starting...")
    tk.Label(wrap, textvariable=status_var, font=(FONT_FAMILY, 9), bg=COLORS["card_bg"],
              fg=COLORS["text_secondary"]).pack(pady=(10, 12))
    pb = ttk.Progressbar(wrap, mode="indeterminate", length=340)
    pb.pack()
    pb.start(12)

    result = {}

    def on_status(msg):
        root.after(0, lambda: status_var.set(msg))

    def worker():
        try:
            df, meta = load_and_clean_data(status_cb=on_status)
            result["df"] = df
            result["meta"] = meta
        except DataLoadError as e:
            result["error"] = e
        except Exception as e:
            log_exception("startup load", e)
            result["error"] = DataLoadError("Unexpected error while loading data",
                                             f"{e}\n\nSee fake_news_gui_error.log for details.")
        root.after(0, root.quit)

    threading.Thread(target=worker, daemon=True).start()
    root.mainloop()

    error = result.get("error")
    if error is not None:
        pb.stop()
        try:
            root.destroy()
        except Exception:
            pass
        # A fresh root for the error dialog, since the splash root is gone.
        err_root = tk.Tk()
        err_root.withdraw()
        messagebox.showerror(error.title, error.detail)
        err_root.destroy()
        return

    df, meta = result["df"], result["meta"]

    # Reuse the same root window for the main app (avoids creating a
    # second Tk() instance, which Tkinter does not support cleanly).
    for widget in root.winfo_children():
        widget.destroy()
    root.resizable(True, True)
    if sys.platform.startswith("win"):
        try:
            root.state("zoomed")
        except Exception:
            pass  # not fatal - app still opens at its default size

    try:
        FakeNewsExplorerApp(root, df, meta)
    except Exception as e:
        log_exception("building main application", e)
        messagebox.showerror("Something went wrong",
                              "The application could not start. The problem has been logged to "
                              f"{LOG_PATH}.")
        root.destroy()
        return

    root.mainloop()


def main():
    try:
        run_splash_then_launch()
    except Exception as e:  # last-resort safety net
        log_exception("fatal top-level error", e)
        try:
            err_root = tk.Tk()
            err_root.withdraw()
            messagebox.showerror("Fake News Dataset Explorer",
                                  "A fatal error occurred and the application must close.\n\n"
                                  f"Details have been logged to {LOG_PATH}.")
            err_root.destroy()
        except Exception:
            print("Fatal error:", e, file=sys.stderr)


if __name__ == "__main__":
    main()
