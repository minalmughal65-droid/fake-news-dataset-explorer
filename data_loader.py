"""
data_loader.py
----------------
Loads, merges, and cleans the ISOT Fake/Real News dataset (Fake.csv + True.csv).
This is the backend data layer used by analysis.py and main.py (the GUI).
"""

import os
import pandas as pd


class NewsDataset:
    """Handles loading, merging, and cleaning of the fake/real news CSV files."""

    def __init__(self, fake_path="Fake.csv", true_path="True.csv"):
        self.fake_path = fake_path
        self.true_path = true_path
        self.data = None          # merged + cleaned DataFrame
        self.rows_removed = 0     # populated after clean()

    def load_and_merge(self):
        """Load both CSV files, tag each row with a label, and merge into one DataFrame."""
        if not os.path.exists(self.fake_path):
            raise FileNotFoundError(f"Could not find {self.fake_path}")
        if not os.path.exists(self.true_path):
            raise FileNotFoundError(f"Could not find {self.true_path}")

        fake_df = pd.read_csv(self.fake_path)
        true_df = pd.read_csv(self.true_path)

        fake_df["label"] = "Fake"
        true_df["label"] = "Real"

        self.data = pd.concat([fake_df, true_df], ignore_index=True)
        return self.data

    def clean(self):
        """Remove duplicates/missing rows, standardize text fields, and parse dates."""
        if self.data is None:
            self.load_and_merge()

        before = len(self.data)

        # Drop rows missing essential fields
        self.data.dropna(subset=["title", "text"], inplace=True)

        # Standardize whitespace FIRST, so duplicate detection isn't fooled by
        # rows that differ only in leading/trailing whitespace
        self.data["title"] = self.data["title"].astype(str).str.strip()
        self.data["text"] = self.data["text"].astype(str).str.strip()
        self.data["subject"] = self.data["subject"].astype(str).str.strip()

        # Remove known crawler/boilerplate artifacts (documented issue with this
        # dataset — e.g. see Phoenyx83/ISOT-Fake-News-Dataset-FineTuned-2022 on
        # HuggingFace). These are site captions/credits, not article content, and
        # would otherwise pollute word-frequency analysis with words like
        # "featured", "image", "via", "getty".
        self.data["text"] = self.data["text"].str.replace(
            r"Featured\s+[Ii]mage[sd]?\b.*$", "", regex=True, case=False
        )
        self.data["text"] = self.data["text"].str.replace(
            r"21st Century Wire says", "", regex=True, case=False
        )
        self.data["text"] = self.data["text"].str.strip()

        # Drop duplicate articles (same title + text)
        self.data.drop_duplicates(subset=["title", "text"], inplace=True)

        # Remove rows with empty/whitespace-only text (some fake news rows are blank)
        self.data = self.data[self.data["text"].astype(bool)]

        # Parse dates. This dataset mixes multiple date formats in one column
        # (e.g. "Mar 17, 2017", "December 2, 2017", "19-Feb-18"), so we use
        # format="mixed" to parse each value on its own terms rather than
        # letting pandas infer a single format for the whole column (which
        # silently nulls out anything that doesn't match the guessed format).
        # A small number of rows in the raw Fake.csv contain a URL instead of
        # a date (a known quirk of this dataset) — those correctly become NaT.
        self.data["date_parsed"] = pd.to_datetime(
            self.data["date"], errors="coerce", format="mixed"
        )

        # Derived helper columns used across the analysis module
        self.data["word_count"] = self.data["text"].str.split().str.len()
        self.data["char_count"] = self.data["text"].str.len()
        self.data["title_word_count"] = self.data["title"].str.split().str.len()

        # Remove degenerate rows: some Fake.csv entries are video-embed posts
        # where the crawler captured no real article body — just a bare URL,
        # or a one-line caption ("Read more: TMZ", "Watch:", "Enjoy!", "Ouch!").
        # Manually inspected every row with word_count<=3 (25 rows) and every
        # "Read more"/"Via" stub up to word_count<=6 (additional ~80 rows) —
        # 100% are content-less video-teaser captions, not genuine short
        # articles, all confined to Fake.csv. Confirmed as a known issue with
        # this dataset (crawler artifact on video-only posts).
        is_bare_url = self.data["text"].str.match(r"^https?://\S+$", na=False)
        is_stub = (
            self.data["word_count"] <= 6
        ) & self.data["text"].str.match(r"^(Read more|Via)\b", case=False, na=False)
        is_content_less = self.data["word_count"] <= 3
        self.data = self.data[~(is_bare_url | is_stub | is_content_less)]

        self.data.reset_index(drop=True, inplace=True)

        after = len(self.data)
        self.rows_removed = before - after
        return self.data

    def get_data(self):
        """Return the cleaned DataFrame, running load+clean first if needed."""
        if self.data is None:
            self.load_and_merge()
            self.clean()
        return self.data

    def summary(self):
        """Quick text summary for console/debug use."""
        if self.data is None:
            self.get_data()
        return {
            "total_rows": len(self.data),
            "fake_count": int((self.data["label"] == "Fake").sum()),
            "real_count": int((self.data["label"] == "Real").sum()),
            "rows_removed_in_cleaning": self.rows_removed,
            "columns": list(self.data.columns),
        }


if __name__ == "__main__":
    ds = NewsDataset()
    ds.load_and_merge()
    ds.clean()
    print(ds.summary())
