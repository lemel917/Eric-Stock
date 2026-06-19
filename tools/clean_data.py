#!/usr/bin/env python3
"""data/*.csv 清理工具 (Stock-5xz)。

修正審查發現的三類資料污染：
1. 完全重複的資料列（0050.csv 約 39% 重複）→ 依時間戳去重
2. 同檔混用時區 +08:00 / +00:00 → 全部正規化到單一時區 (Asia/Taipei)
3. 重複/亂序時間戳 → 依時間排序

注意：這是「破壞性」清理（就地覆寫）。預設為 --dry-run 只報告不寫入，
務必確認後再加 --write 實際覆寫。

用法：
    python tools/clean_data.py --dry-run      # 只報告各檔重複/時區狀況
    python tools/clean_data.py --write         # 實際清理並覆寫 data/*.csv
"""
import argparse
import glob
import os

import pandas as pd

DEFAULT_TZ = "Asia/Taipei"


def clean_ohlc(df, tz=DEFAULT_TZ):
    """清理單一 OHLC DataFrame：去重 + 統一時區 + 排序。

    第一欄視為時間欄（Datetime 或 Date）。混用時區的字串先一律解析為 UTC，
    再轉成目標時區，確保表示法一致；之後依時間戳去重(保留第一筆)並排序。

    Parameters
    ----------
    df : pd.DataFrame  原始讀入的 CSV
    tz : str           目標時區

    Returns
    -------
    (cleaned_df, stats) : tuple[pd.DataFrame, dict]
        stats 含 rows_in / rows_out / duplicates_removed
    """
    if df.shape[1] == 0:
        return df, {"rows_in": 0, "rows_out": 0, "duplicates_removed": 0}

    dtcol = df.columns[0]
    rows_in = len(df)

    parsed = pd.to_datetime(df[dtcol], utc=True, errors="coerce")
    out = df.copy()
    out[dtcol] = parsed
    out = out.dropna(subset=[dtcol])
    out = out.drop_duplicates(subset=[dtcol], keep="first")
    out = out.sort_values(dtcol)
    # tz_convert 需要 tz-aware（utc=True 已保證）；轉成單一目標時區
    out[dtcol] = out[dtcol].dt.tz_convert(tz)
    out = out.reset_index(drop=True)

    rows_out = len(out)
    return out, {
        "rows_in": rows_in,
        "rows_out": rows_out,
        "duplicates_removed": rows_in - rows_out,
    }


def main():
    parser = argparse.ArgumentParser(description="清理 data/*.csv 的重複列與時區")
    parser.add_argument("--data-dir", default=None,
                        help="資料目錄 (預設專案根的 data/)")
    parser.add_argument("--write", action="store_true",
                        help="實際覆寫檔案 (預設只 dry-run 報告)")
    args = parser.parse_args()

    data_dir = args.data_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    files = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
    print(f"掃描 {len(files)} 個檔案於 {data_dir} "
          f"({'WRITE' if args.write else 'DRY-RUN'})")

    total_dups = 0
    for f in files:
        try:
            df = pd.read_csv(f)
        except Exception as e:
            print(f"  ⚠️ 讀取失敗 {os.path.basename(f)}: {e}")
            continue
        cleaned, stats = clean_ohlc(df)
        total_dups += stats["duplicates_removed"]
        if stats["duplicates_removed"] > 0:
            print(f"  {os.path.basename(f)}: -{stats['duplicates_removed']} "
                  f"重複列 ({stats['rows_in']}→{stats['rows_out']})")
        if args.write:
            cleaned.to_csv(f, index=False)

    print(f"完成。共可移除 {total_dups} 重複列"
          f"{'（已寫入）' if args.write else '（dry-run，未寫入）'}")


if __name__ == "__main__":
    main()
