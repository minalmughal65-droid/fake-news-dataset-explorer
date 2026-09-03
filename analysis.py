"""
analysis.py
------------
All analytical queries for the Fake News Dataset Explorer.
Uses pandas + numpy on top of the cleaned DataFrame produced by data_loader.py.

Every method returns a pandas DataFrame or a plain dict so the GUI layer
(main.py) can display it in a table or a chart without extra conversion.
"""

import re
from collections import Counter
import numpy as np
import pandas as pd

# Small built-in stopword list (no external downloads needed for a beginner project)
STOPWORDS = set("""
a an the and or but if while is are was were be been being to of in on for
with as by at from this that these those it its it's he she they them his
her their our your my i you we us not no do does did doing have has had
will would could should can may might shall said says say also than then
so such just about into over after before up down out more most other
than which who whom what when where why how all any both each few more
most some such no nor only own same too very s t will just don should now
reuters new york washington
""".split())


class NewsAnalyzer:
    """Runs all statistical / analytical queries over a cleaned news DataFrame."""

    def __init__(self, dataframe: pd.DataFrame):
        self.df = dataframe

    # ---------- 1. Category / subject distribution ----------
    def category_distribution(self) -> pd.DataFrame:
        result = (
            self.df.groupby(["label", "subject"])
            .size()
            .reset_index(name="count")
            .sort_values(["label", "count"], ascending=[True, False])
        )
        return result

    # ---------- 2. Text length analysis (NumPy stats) ----------
    def text_length_stats(self) -> pd.DataFrame:
        rows = []
        for label, group in self.df.groupby("label"):
            wc = group["word_count"].to_numpy()
            rows.append({
                "label": label,
                "avg_word_count": round(float(np.mean(wc)), 2),
                "median_word_count": float(np.median(wc)),
                "std_word_count": round(float(np.std(wc)), 2),
                "min_word_count": int(np.min(wc)),
                "max_word_count": int(np.max(wc)),
            })
        return pd.DataFrame(rows)

    # ---------- 3. Source / subject comparison ----------
    def source_comparison(self) -> pd.DataFrame:
        pivot = self.df.pivot_table(
            index="subject", columns="label", values="text",
            aggfunc="count", fill_value=0
        ).reset_index()
        return pivot

    # ---------- 4. Most common words ----------
    def most_common_words(self, label: str = None, n: int = 20) -> pd.DataFrame:
        subset = self.df if label is None else self.df[self.df["label"] == label]
        counter = Counter()
        # Sample up to 4000 articles for speed on large datasets; still statistically representative
        sample = subset["text"] if len(subset) <= 4000 else subset["text"].sample(4000, random_state=42)
        for text in sample:
            words = re.findall(r"[a-zA-Z']+", text.lower())
            counter.update(w for w in words if w not in STOPWORDS and len(w) > 2)
        common = counter.most_common(n)
        return pd.DataFrame(common, columns=["word", "count"])

    # ---------- 5. Duplicate / cleaning report ----------
    def cleaning_report(self, rows_removed: int) -> dict:
        return {
            "rows_removed": rows_removed,
            "final_row_count": len(self.df),
        }

    # ---------- 6. Longest articles ----------
    def top_longest_articles(self, n: int = 10) -> pd.DataFrame:
        return self.df.nlargest(n, "word_count")[["title", "label", "subject", "word_count"]]

    # ---------- 7. Shortest articles ----------
    def top_shortest_articles(self, n: int = 10) -> pd.DataFrame:
        return self.df.nsmallest(n, "word_count")[["title", "label", "subject", "word_count"]]

    # ---------- 8. Monthly trend ----------
    def monthly_trends(self) -> pd.DataFrame:
        valid = self.df.dropna(subset=["date_parsed"]).copy()
        valid["year_month"] = valid["date_parsed"].dt.to_period("M").astype(str)
        result = (
            valid.groupby(["year_month", "label"])
            .size()
            .reset_index(name="count")
            .sort_values("year_month")
        )
        return result

    # ---------- 9. Average title length by label ----------
    def avg_title_length(self) -> pd.DataFrame:
        result = (
            self.df.groupby("label")["title_word_count"]
            .agg(avg_title_words="mean", max_title_words="max")
            .reset_index()
        )
        result["avg_title_words"] = result["avg_title_words"].round(2)
        return result

    # ---------- 10. Average article length per subject ----------
    def subject_avg_length(self) -> pd.DataFrame:
        return (
            self.df.groupby(["subject", "label"])["word_count"]
            .mean()
            .round(1)
            .reset_index(name="avg_word_count")
        )

    # ---------- 11. Overall label balance ----------
    def label_balance(self) -> pd.DataFrame:
        counts = self.df["label"].value_counts().reset_index()
        counts.columns = ["label", "count"]
        counts["percentage"] = round(counts["count"] / counts["count"].sum() * 100, 2)
        return counts


if __name__ == "__main__":
    from data_loader import NewsDataset

    ds = NewsDataset()
    df = ds.get_data()
    an = NewsAnalyzer(df)

    print("\n--- Label balance ---")
    print(an.label_balance())
    print("\n--- Text length stats ---")
    print(an.text_length_stats())
    print("\n--- Top common words (Fake) ---")
    print(an.most_common_words(label="Fake", n=10))
    print("\n--- Top common words (Real) ---")
    print(an.most_common_words(label="Real", n=10))
