"""
main.py
--------
Fake News Dataset Explorer — Tkinter GUI

Run with:  python main.py
Requires:  pandas, numpy, matplotlib   (tkinter ships with Python)

This is the front-end. All real logic lives in data_loader.py (loading/cleaning)
and analysis.py (analytical queries) so the GUI code just calls those and displays
the results in tables or charts.
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import pandas as pd
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from data_loader import NewsDataset
from analysis import NewsAnalyzer

# ---------- Color / style constants ----------
BG_SIDEBAR = "#1f2937"      # dark slate
BG_MAIN = "#f4f5f7"         # light gray
ACCENT = "#2563eb"          # blue
ACCENT_HOVER = "#1d4ed8"
TEXT_LIGHT = "#e5e7eb"
FAKE_COLOR = "#ef4444"
REAL_COLOR = "#22c55e"


class FakeNewsExplorerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Fake News Dataset Explorer")
        self.root.geometry("1150x700")
        self.root.minsize(950, 600)
        self.root.configure(bg=BG_MAIN)

        self.dataset = NewsDataset(
            fake_path=self._resource_path("Fake.csv"),
            true_path=self._resource_path("True.csv"),
        )
        self.df = None
        self.analyzer = None
        self.current_table_df = None  # whatever is currently shown, for export

        self._build_layout()
        self._load_data_on_start()

    @staticmethod
    def _resource_path(filename):
        base = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base, filename)

    # ---------------- Layout ----------------
    def _build_layout(self):
        # Top header bar
        header = tk.Frame(self.root, bg=ACCENT, height=56)
        header.pack(side="top", fill="x")
        tk.Label(
            header, text="📰  Fake News Dataset Explorer",
            bg=ACCENT, fg="white", font=("Segoe UI", 16, "bold")
        ).pack(side="left", padx=16, pady=10)

        self.status_var = tk.StringVar(value="Loading dataset...")
        tk.Label(
            header, textvariable=self.status_var, bg=ACCENT, fg="white",
            font=("Segoe UI", 9)
        ).pack(side="right", padx=16)

        # Body: sidebar + content
        body = tk.Frame(self.root, bg=BG_MAIN)
        body.pack(side="top", fill="both", expand=True)

        self.sidebar = tk.Frame(body, bg=BG_SIDEBAR, width=230)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.content = tk.Frame(body, bg=BG_MAIN)
        self.content.pack(side="left", fill="both", expand=True, padx=14, pady=14)

        self._build_sidebar_buttons()

        # Bottom export bar
        footer = tk.Frame(self.root, bg="#e5e7eb", height=42)
        footer.pack(side="bottom", fill="x")
        self.export_btn = tk.Button(
            footer, text="⬇ Export Current View to CSV", command=self.export_current_view,
            bg="white", relief="groove", cursor="hand2", state="disabled"
        )
        self.export_btn.pack(side="right", padx=10, pady=6)

    def _build_sidebar_buttons(self):
        tk.Label(
            self.sidebar, text="FEATURES", bg=BG_SIDEBAR, fg="#9ca3af",
            font=("Segoe UI", 9, "bold")
        ).pack(anchor="w", padx=16, pady=(16, 4))

        buttons = [
            ("🏠  Overview", self.show_overview),
            ("🧹  Dataset Cleaning", self.show_cleaning_report),
            ("📊  Category Distribution", self.show_category_distribution),
            ("📏  Text Length Analysis", self.show_text_length),
            ("🔀  Source Comparison", self.show_source_comparison),
            ("🔠  Most Common Words", self.show_common_words),
            ("📈  Monthly Trends", self.show_monthly_trends),
            ("📰  Longest / Shortest", self.show_longest_shortest),
            ("✏️  Title Length", self.show_title_length),
        ]
        for label, cmd in buttons:
            self._sidebar_button(label, cmd)

    def _sidebar_button(self, text, command):
        btn = tk.Button(
            self.sidebar, text=text, command=command,
            bg=BG_SIDEBAR, fg=TEXT_LIGHT, activebackground=ACCENT_HOVER,
            activeforeground="white", bd=0, anchor="w", padx=16, pady=10,
            font=("Segoe UI", 10), cursor="hand2"
        )
        btn.pack(fill="x")

        def on_enter(e):
            btn.configure(bg=ACCENT_HOVER)

        def on_leave(e):
            btn.configure(bg=BG_SIDEBAR)

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)

    # ---------------- Data loading ----------------
    def _load_data_on_start(self):
        try:
            self.df = self.dataset.get_data()
            self.analyzer = NewsAnalyzer(self.df)
            self.status_var.set(
                f"Loaded {len(self.df):,} articles  |  "
                f"Fake: {(self.df['label']=='Fake').sum():,}  "
                f"Real: {(self.df['label']=='Real').sum():,}"
            )
            self.show_overview()
        except FileNotFoundError as e:
            messagebox.showerror("Dataset not found", str(e))
            self.status_var.set("Dataset not found.")

    # ---------------- Content area helpers ----------------
    def _clear_content(self):
        for widget in self.content.winfo_children():
            widget.destroy()

    def _content_title(self, text):
        tk.Label(
            self.content, text=text, bg=BG_MAIN, fg="#111827",
            font=("Segoe UI", 14, "bold")
        ).pack(anchor="w", pady=(0, 10))

    def _show_table(self, df: pd.DataFrame, max_rows=300):
        """Render a DataFrame as a scrollable ttk.Treeview table."""
        self.current_table_df = df
        self.export_btn.configure(state="normal")

        frame = tk.Frame(self.content, bg=BG_MAIN)
        frame.pack(fill="both", expand=True)

        tree = ttk.Treeview(frame, columns=list(df.columns), show="headings")
        for col in df.columns:
            tree.heading(col, text=col)
            tree.column(col, width=140, anchor="w")

        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        for _, row in df.head(max_rows).iterrows():
            tree.insert("", "end", values=list(row))

    def _show_chart(self, plot_func, figsize=(7, 4)):
        fig = Figure(figsize=figsize, dpi=100)
        ax = fig.add_subplot(111)
        plot_func(ax)
        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=self.content)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    # ---------------- Feature views ----------------
    def show_overview(self):
        self._clear_content()
        self._content_title("Overview")
        self.export_btn.configure(state="disabled")

        summary = self.dataset.summary()
        info = (
            f"Total articles: {summary['total_rows']:,}\n"
            f"Fake: {summary['fake_count']:,}   |   Real: {summary['real_count']:,}\n"
            f"Rows removed while cleaning (duplicates / missing / blank): "
            f"{summary['rows_removed_in_cleaning']:,}"
        )
        tk.Label(self.content, text=info, bg=BG_MAIN, justify="left",
                 font=("Segoe UI", 11)).pack(anchor="w", pady=(0, 10))

        def plot(ax):
            counts = self.df["label"].value_counts()
            colors = [FAKE_COLOR if l == "Fake" else REAL_COLOR for l in counts.index]
            ax.bar(counts.index, counts.values, color=colors)
            ax.set_title("Fake vs Real Article Count")
            ax.set_ylabel("Articles")

        self._show_chart(plot)

    def show_cleaning_report(self):
        self._clear_content()
        self._content_title("Dataset Cleaning Report")
        self.export_btn.configure(state="disabled")
        report = self.analyzer.cleaning_report(self.dataset.rows_removed)
        text = (
            f"Rows removed (duplicates, missing titles/text, blank text): "
            f"{report['rows_removed']:,}\n"
            f"Final clean row count: {report['final_row_count']:,}\n\n"
            "Cleaning steps applied:\n"
            "  • Dropped rows with missing title/text\n"
            "  • Dropped duplicate articles (same title + text)\n"
            "  • Removed blank/whitespace-only articles\n"
            "  • Standardized whitespace in title/text/subject\n"
            "  • Parsed publish dates into a proper date format"
        )
        tk.Label(self.content, text=text, bg=BG_MAIN, justify="left",
                 font=("Segoe UI", 11)).pack(anchor="w")

    def show_category_distribution(self):
        self._clear_content()
        self._content_title("Category (Subject) Distribution")
        df = self.analyzer.category_distribution()
        self._show_table(df)

    def show_text_length(self):
        self._clear_content()
        self._content_title("Text Length Analysis")
        df = self.analyzer.text_length_stats()
        self._show_table(df)

        def plot(ax):
            for label, color in [("Fake", FAKE_COLOR), ("Real", REAL_COLOR)]:
                data = self.df[self.df["label"] == label]["word_count"]
                ax.hist(data, bins=40, alpha=0.6, label=label, color=color, range=(0, 1500))
            ax.set_title("Word Count Distribution")
            ax.set_xlabel("Words per article")
            ax.legend()

        self._show_chart(plot)

    def show_source_comparison(self):
        self._clear_content()
        self._content_title("Source / Subject Comparison")
        df = self.analyzer.source_comparison()

        overlap = set(self.df[self.df["label"] == "Fake"]["subject"]) & \
                  set(self.df[self.df["label"] == "Real"]["subject"])
        if not overlap:
            note = (
                "Finding: Fake and Real articles use completely different subject "
                "categories — zero overlap. This means the 'subject' field alone "
                "almost perfectly separates the two classes. This is a documented "
                "characteristic of this dataset (fake articles are tagged News / "
                "politics / left-news / Government News / US_News / Middle-east; "
                "real articles are only politicsNews / worldnews), not an error in "
                "this analysis — worth mentioning in your report as a data insight."
            )
            tk.Label(
                self.content, text=note, bg="#fef3c7", fg="#78350f",
                justify="left", wraplength=820, font=("Segoe UI", 9),
                padx=10, pady=8
            ).pack(anchor="w", fill="x", pady=(0, 10))

        self._show_table(df)

    def show_common_words(self):
        self._clear_content()
        self._content_title("Most Common Words (Fake vs Real)")

        fake_words = self.analyzer.most_common_words(label="Fake", n=15)
        real_words = self.analyzer.most_common_words(label="Real", n=15)
        merged = fake_words.rename(columns={"word": "fake_word", "count": "fake_count"})
        merged["real_word"] = real_words["word"]
        merged["real_count"] = real_words["count"]
        self._show_table(merged)

    def show_monthly_trends(self):
        self._clear_content()
        self._content_title("Monthly Publishing Trends")
        df = self.analyzer.monthly_trends()

        def plot(ax):
            for label, color in [("Fake", FAKE_COLOR), ("Real", REAL_COLOR)]:
                sub = df[df["label"] == label]
                ax.plot(sub["year_month"], sub["count"], label=label, color=color, marker="o")
            ax.set_title("Articles per Month")
            ax.tick_params(axis="x", rotation=75, labelsize=7)
            ax.legend()

        self._show_chart(plot, figsize=(8, 4.2))

    def show_longest_shortest(self):
        self._clear_content()
        self._content_title("Longest & Shortest Articles")
        longest = self.analyzer.top_longest_articles(10)
        shortest = self.analyzer.top_shortest_articles(10)
        combined = pd.concat(
            [longest.assign(type="Longest"), shortest.assign(type="Shortest")],
            ignore_index=True
        )
        self._show_table(combined)

    def show_title_length(self):
        self._clear_content()
        self._content_title("Average Title Length")
        df = self.analyzer.avg_title_length()
        self._show_table(df)

    # ---------------- Export ----------------
    def export_current_view(self):
        if self.current_table_df is None:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV file", "*.csv")],
            initialfile="report_export.csv"
        )
        if path:
            self.current_table_df.to_csv(path, index=False)
            messagebox.showinfo("Exported", f"Saved to {path}")


def main():
    root = tk.Tk()
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    app = FakeNewsExplorerApp(root)

    # Test-only hook: auto-close after N ms when GUI_TEST=1 (used for automated verification)
    if os.environ.get("GUI_TEST") == "1":
        root.after(2500, root.destroy)

    root.mainloop()


if __name__ == "__main__":
    main()
