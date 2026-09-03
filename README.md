# fake-news-dataset-explorer
Tkinter GUI for exploring the ISOT Fake/Real News dataset

# Fake News Dataset Explorer

A Tkinter-based desktop GUI for exploring the ISOT Fake/Real News dataset (38,566 cleaned articles). Built as a BS Artificial Intelligence course project (Semester 4).

## What it does

Loads, cleans, and analyzes real vs. fake news articles, then presents the findings through an interactive desktop interface — no need to read raw code or CSV files.

**Key finding:** Fake and Real articles use completely non-overlapping subject tags — a notable characteristic of this dataset.

## Features

- Dataset overview and cleaning report
- Category/subject distribution
- Text length analysis (word count statistics + histogram)
- Source/subject comparison
- Most common words (Fake vs Real)
- Monthly publishing trends
- Longest/shortest articles
- Average title length comparison
- Export any view to CSV

## Files

- `main.py` — base GUI version
- `fake_news_gui_v3 (2).py` — Premium Analytics Edition (expanded UI, more features, background threading, error handling)
- `data_loader.py` — loads, merges, and cleans the raw CSV dataset
- `analysis.py` — 11 analytical query methods (Pandas/NumPy)

## How to run

1. Install requirements: `pip install pandas numpy matplotlib`
2. Download the [ISOT Fake/Real News dataset](https://www.kaggle.com/datasets/clmentbisaillon/fake-and-real-news-dataset) (`Fake.csv` and `True.csv`) and place them in the same folder as the code
3. Run: `python main.py` (base version) or `python "fake_news_gui_v3 (2).py"` (premium version)

## Tech stack

Python, Tkinter, Pandas, NumPy, Matplotlib

## Author

Minal Akmal — BS Artificial Intelligence Student


