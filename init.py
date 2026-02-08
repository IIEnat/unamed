import json
import re
from pathlib import Path
import pandas as pd

# -----------------------------
# Paths / config
# -----------------------------
DATA_DIR = Path("data")
INSTANCE_DIR = Path("instance")

RAW_FILES = ["2023.csv", "2024.csv", "2025.csv", "2026.csv"] 
CATEGORIES_JSON = INSTANCE_DIR / "categories.json"
OUTPUT_CSV = INSTANCE_DIR / "categorised.csv"

REQUIRED_OUT_COLS = ["date", "account", "narration", "debit", "credit", "balance", "category"]

RENAME_MAP = {
    "Transaction Date": "date",
    "Account Number": "account",
    "Narration": "narration",
    "Debit": "debit",
    "Credit": "credit",
    "Balance": "balance",
    "Transaction Type": "txn_type",
}

TRANSFER_TYPES = {"TFC", "TFD"}


# -----------------------------
# Helpers
# -----------------------------
def normalise_text(s: str) -> str:
    s = "" if s is None else str(s)
    s = s.strip().lower()
    return re.sub(r"\s+", " ", s)


def load_categories(path: Path) -> dict:
    """
    Expected structure:
    {
      "keywords": { "coles": "groceries", ... },
      "exact": { "jake ...": "other", ... }
    }
    Backwards compat: flat dict treated as keywords.
    """
    if not path.exists():
        return {"keywords": {}, "exact": {}}

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and ("keywords" in data or "exact" in data):
        keywords_raw = data.get("keywords", {}) or {}
        exact_raw = data.get("exact", {}) or {}
        return {
            "keywords": {normalise_text(k): normalise_text(v) for k, v in keywords_raw.items()},
            "exact": {normalise_text(k): normalise_text(v) for k, v in exact_raw.items()},
        }

    flat = {normalise_text(k): normalise_text(v) for k, v in (data or {}).items()}
    return {"keywords": flat, "exact": {}}


def save_categories(path: Path, categories: dict) -> None:
    keywords = categories.get("keywords", {}) or {}
    exact = categories.get("exact", {}) or {}

    ordered = {
        "keywords": dict(sorted(keywords.items(), key=lambda kv: (kv[1], kv[0]))),
        "exact": dict(sorted(exact.items(), key=lambda kv: (kv[1], kv[0]))),
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(ordered, f, ensure_ascii=False, indent=2)


def pick_category(narration: str, txn_type: str, categories: dict) -> tuple[str | None, str | None]:
    """
    Returns (category, method) where method in {"exact", "keyword", "txn_type"} or None.
    """
    t = normalise_text(txn_type).upper()
    if t in TRANSFER_TYPES:
        return "transfer", "txn_type"

    text = normalise_text(narration)
    exact = categories["exact"]
    keywords = categories["keywords"]

    if text in exact:
        return exact[text], "exact"

    for key in sorted(keywords.keys(), key=len, reverse=True):
        if key and key in text:
            return keywords[key], "keyword"

    return None, None


def choose_category_from_list(known_categories: list[str]) -> str:
    INCOME = {"allowance", "interest", "job", "prizes", "returns"}
    EXPENSE = {
        "church", "drinks", "education", "entertainment", "events", "fashion",
        "fitness", "food", "groceries", "health", "home improvements",
        "shopping", "stationery", "tech", "transport", "travel",
        "utilities", "investments", "gifts", "penalties",
    }

    income = [c for c in known_categories if c in INCOME]
    expense = [c for c in known_categories if c in EXPENSE]
    ordered = income + expense
    n = len(ordered)

    def print_block(title, items, start_idx):
        if not items:
            return start_idx
        print(f"{title}:")
        for i in range(0, len(items), 4):
            chunk = items[i : i + 4]
            line = []
            for j, cat in enumerate(chunk):
                num = start_idx + i + j
                line.append(f"{num:>2}) {cat:<16}")
            print("   ".join(line))
        return start_idx + len(items)

    print("\nChoose a category:")
    print("0) uncategorised        1) void        2) reimbursement")

    idx = 3
    idx = print_block("Income", income, idx)
    idx = print_block("Expenses", expense, idx)

    while True:
        raw = input("\nEnter number: ").strip()
        if not raw.isdigit():
            print("Please enter a number.")
            continue

        choice = int(raw)
        if choice == 0:
            return "uncategorised"
        if choice == 1:
            return "void"
        if choice == 2:
            return "reimbursement"
        if 3 <= choice <= (n + 2):
            return ordered[choice - 3]

        print("Invalid choice. Try again.")


def read_and_merge_raw_files(data_dir: Path, filenames: list[str]) -> pd.DataFrame:
    paths = [data_dir / f for f in filenames]
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Missing raw CSV(s): {[str(p) for p in missing]}")

    dfs = [pd.read_csv(p) for p in paths]
    df = pd.concat(dfs, ignore_index=True)

    if "Transaction Date" not in df.columns:
        raise ValueError(f"Raw CSVs must include 'Transaction Date'. Found: {list(df.columns)}")

    df["Transaction Date"] = pd.to_datetime(df["Transaction Date"], dayfirst=True, errors="coerce")
    df = df.sort_values("Transaction Date")
    return df


def normalise_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in RENAME_MAP.keys() if c not in df.columns]
    if missing:
        raise ValueError(f"Raw data is missing columns: {missing}. Found: {list(df.columns)}")

    df = df.rename(columns=RENAME_MAP)

    if "BSB Number" in df.columns:
        df["account"] = (
            df["BSB Number"].astype(str).str.strip()
            + "-"
            + df["account"].astype(str).str.strip()
        )
    else:
        df["account"] = df["account"].astype(str).str.strip()

    df["narration"] = df["narration"].astype(str).fillna("").str.strip()
    df["date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")
    df["txn_type"] = df["txn_type"].astype(str).fillna("").str.strip().str.upper()

    return df


def categorise(df: pd.DataFrame, categories: dict) -> tuple[pd.DataFrame, int]:
    known_categories = sorted(set(categories["keywords"].values()) | set(categories["exact"].values()))
    categories_out = []
    user_added = 0

    print("\n--- Categorising transactions ---\n")

    for _, row in df.iterrows():
        narration = row["narration"]
        txn_type = row.get("txn_type", "")

        date_str = row["date"].date().isoformat() if pd.notna(row["date"]) else "N/A"
        debit = row.get("debit", "")
        credit = row.get("credit", "")
        amount_str = f"Debit={debit} Credit={credit}"

        cat, method = pick_category(narration, txn_type, categories)

        if cat is None:
            print("--------------------------")
            print("Uncategorised transaction:")
            print(f"  Date:  {date_str}")
            print(f"  Desc:  {narration}")
            print(f"  {amount_str}")

            chosen = choose_category_from_list(known_categories)

            # add to exact so this exact narration matches next time
            categories["exact"][normalise_text(narration)] = normalise_text(chosen)
            user_added += 1

            if chosen not in known_categories and chosen != "uncategorised":
                known_categories = sorted(set(known_categories) | {chosen})

            cat, method = chosen, "manual->exact"

        categories_out.append(cat)
        print(f"{date_str} | {amount_str} | {narration}  ->  {cat}  [{method}]")

    df = df.copy()
    df["category"] = categories_out
    return df, user_added


def build_output(df: pd.DataFrame) -> pd.DataFrame:
    out = df[REQUIRED_OUT_COLS].copy()
    out["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return out


def main() -> None:
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)

    # 1) merge raw yearly files (no merged.csv written)
    merged = read_and_merge_raw_files(DATA_DIR, RAW_FILES)

    # 2) normalise to internal schema
    df = normalise_dataframe(merged)

    # 3) load categories + categorise
    categories = load_categories(CATEGORIES_JSON)
    df, user_added = categorise(df, categories)

    # 4) persist updated categories if needed
    if user_added:
        save_categories(CATEGORIES_JSON, categories)
        print(f"\nUpdated categories.json with {user_added} new exact rule(s): {CATEGORIES_JSON}")

    # 5) write final output only
    out = build_output(df)
    out.to_csv(OUTPUT_CSV, index=False)
    print(f"\nSaved: {OUTPUT_CSV.resolve()}")


if __name__ == "__main__":
    main()
