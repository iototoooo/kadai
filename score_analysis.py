import csv
import io
import statistics
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

# Windows コンソールの文字コード問題を回避
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CSV_FILE = "課題2.csv"


# ── 表示幅ユーティリティ（全角文字対応） ───────────────────────────────────────────

def wlen(s):
    """端末での表示幅を返す（全角=2、半角=1）。"""
    return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in s)

def wljust(s, width):
    return s + ' ' * max(0, width - wlen(s))

def wrjust(s, width):
    return ' ' * max(0, width - wlen(s)) + s

def wcenter(s, width):
    pad = max(0, width - wlen(s))
    return ' ' * (pad // 2) + s + ' ' * (pad - pad // 2)


# ── データ読み込み ──────────────────────────────────────────────────────────────────

def load_data(filepath: Path):
    rows = []
    with filepath.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            rows.append({
                "名前":  row["名前"].strip(),
                "日付":  row["日付"].strip(),
                "科目":  row["科目"].strip(),
                "スコア": int(row["スコア"].strip()),
            })
    return rows


# ── 表示ユーティリティ ──────────────────────────────────────────────────────────────

def section(title):
    print(f"\n{'═' * 58}")
    print(f"  {title}")
    print('═' * 58)

def divider(width=58):
    print('─' * width)


# ── 各集計レポート ──────────────────────────────────────────────────────────────────

def report_per_person(rows):
    """① 参加者別 基本統計＋得意／苦手科目"""
    section("① 参加者別 スコアサマリー（平均点順）")

    by_person  = defaultdict(list)
    subj_score = defaultdict(dict)
    for r in rows:
        by_person[r["名前"]].append(r["スコア"])
        subj_score[r["名前"]][r["科目"]] = r["スコア"]

    results = [(name, by_person[name], subj_score[name]) for name in by_person]
    results.sort(key=lambda x: statistics.mean(x[1]), reverse=True)

    # 列幅（端末表示幅基準）
    W = dict(rank=4, name=10, avg=6, hi=4, lo=4, best=10)
    # 合計: 4+2+10+2+6+2+4+2+4+2+10+2+8 = 58
    header = (
        wcenter("順位", W["rank"]) + "  " +
        wljust("名前",   W["name"]) + "  " +
        wrjust("平均",   W["avg"])  + "  " +
        wrjust("最高",   W["hi"])   + "  " +
        wrjust("最低",   W["lo"])   + "  " +
        wcenter("得意科目", W["best"]) + "  " +
        "苦手科目"
    )
    divider()
    print(header)
    divider()

    for rank, (name, sc, subj) in enumerate(results, 1):
        best  = max(subj, key=subj.get)
        worst = min(subj, key=subj.get)
        print(
            wcenter(str(rank),                   W["rank"]) + "  " +
            wljust(name,                         W["name"]) + "  " +
            wrjust(f"{statistics.mean(sc):.1f}", W["avg"])  + "  " +
            wrjust(str(max(sc)),                 W["hi"])   + "  " +
            wrjust(str(min(sc)),                 W["lo"])   + "  " +
            wcenter(f"{best}({subj[best]})",     W["best"]) + "  " +
            f"{worst}({subj[worst]})"
        )
    divider()


def report_subject_matrix(rows):
    """② 参加者 × 科目 スコアマトリクス"""
    section("② 参加者 × 科目 スコアマトリクス")

    names    = sorted({r["名前"] for r in rows})
    subjects = sorted({r["科目"] for r in rows})

    score_map = defaultdict(lambda: defaultdict(list))
    for r in rows:
        score_map[r["名前"]][r["科目"]].append(r["スコア"])

    NAME_W = 10
    CELL_W = 6
    AVG_W  = 6
    # 合計: 10 + (2+6)×5 + 2+6 = 58
    total_w = NAME_W + (2 + CELL_W) * len(subjects) + 2 + AVG_W

    header = (
        wljust("名前", NAME_W) +
        "".join(f"  {wcenter(s, CELL_W)}" for s in subjects) +
        f"  {wrjust('平均', AVG_W)}"
    )
    divider(total_w)
    print(header)
    divider(total_w)

    for name in names:
        cells, all_sc = [], []
        for subj in subjects:
            sc = score_map[name][subj]
            if sc:
                avg = sum(sc) / len(sc)
                cells.append(wcenter(f"{avg:.0f}", CELL_W))
                all_sc.extend(sc)
            else:
                cells.append(wcenter("--", CELL_W))
        overall = sum(all_sc) / len(all_sc) if all_sc else 0
        print(
            wljust(name, NAME_W) +
            "".join(f"  {c}" for c in cells) +
            f"  {wrjust(f'{overall:.1f}', AVG_W)}"
        )

    divider(total_w)
    col_avgs, col_cells = [], []
    for subj in subjects:
        sc = [r["スコア"] for r in rows if r["科目"] == subj]
        a = sum(sc) / len(sc)
        col_avgs.append(a)
        col_cells.append(wcenter(f"{a:.1f}", CELL_W))
    grand_avg = sum(col_avgs) / len(col_avgs)
    print(
        wljust("科目平均", NAME_W) +
        "".join(f"  {c}" for c in col_cells) +
        f"  {wrjust(f'{grand_avg:.1f}', AVG_W)}"
    )
    divider(total_w)


def report_per_subject(rows):
    """③ 科目別 最高点者／最低点者／平均"""
    section("③ 科目別 最高点者 / 最低点者 / 平均点")

    by_subject = defaultdict(list)
    for r in rows:
        by_subject[r["科目"]].append(r)

    # 列幅（端末表示幅基準）
    W = dict(subj=6, avg=6, med=6, hi=4, hi_name=10, lo=4)
    # 合計: 6+2+6+2+6+2+4+1+10+2+4+1+8 = 54（最終列は可変）
    total_w = W["subj"]+2+W["avg"]+2+W["med"]+2+W["hi"]+1+W["hi_name"]+2+W["lo"]+1+8

    header = (
        wljust("科目",   W["subj"])    + "  " +
        wrjust("平均",   W["avg"])     + "  " +
        wrjust("中央値", W["med"])     + "  " +
        wrjust("最高",   W["hi"])      + " " +
        wljust("最高点者", W["hi_name"]) + "  " +
        wrjust("最低",   W["lo"])      + " " +
        "最低点者"
    )
    divider(total_w)
    print(header)
    divider(total_w)

    for subj in sorted(by_subject):
        entries = by_subject[subj]
        sc  = [e["スコア"] for e in entries]
        top    = max(entries, key=lambda e: e["スコア"])
        bottom = min(entries, key=lambda e: e["スコア"])
        print(
            wljust(subj,                          W["subj"])    + "  " +
            wrjust(f"{statistics.mean(sc):.1f}",  W["avg"])     + "  " +
            wrjust(f"{statistics.median(sc):.1f}", W["med"])     + "  " +
            wrjust(str(top["スコア"]),            W["hi"])      + " " +
            wljust(top["名前"],                   W["hi_name"]) + "  " +
            wrjust(str(bottom["スコア"]),         W["lo"])      + " " +
            bottom["名前"]
        )
    divider(total_w)


def report_overall_ranking(rows):
    """④ 総合ランキング TOP3 / BOTTOM3"""
    section("④ 総合ランキング（全スコア平均）")

    by_person = defaultdict(list)
    for r in rows:
        by_person[r["名前"]].append(r["スコア"])

    ranked = sorted(
        by_person.items(),
        key=lambda x: statistics.mean(x[1]),
        reverse=True,
    )
    medals = ["🥇", "🥈", "🥉"]

    print("\n  ▼ TOP 3")
    divider()
    for i, (name, sc) in enumerate(ranked[:3]):
        print(
            f"  {medals[i]} {i+1}位  " +
            wljust(name, 10) +
            f"平均 {statistics.mean(sc):.1f}点  " +
            f"最高 {max(sc)}点 / 最低 {min(sc)}点"
        )

    print("\n  ▼ BOTTOM 3")
    divider()
    for i, (name, sc) in enumerate(ranked[-3:]):
        rank = len(ranked) - 2 + i
        print(
            f"  {rank}位      " +
            wljust(name, 10) +
            f"平均 {statistics.mean(sc):.1f}点  " +
            f"最高 {max(sc)}点 / 最低 {min(sc)}点"
        )
    divider()


# ── メイン ─────────────────────────────────────────────────────────────────────────

def main():
    base_dir = Path(__file__).resolve().parent
    csv_path = base_dir / CSV_FILE

    if not csv_path.exists():
        raise SystemExit(f"ファイルが見つかりません: {csv_path}")

    rows = load_data(csv_path)

    print(f"\n{'★' * 3}  スコア多角分析レポート  {'★' * 3}")
    print(f"  対象: {CSV_FILE}  /  読み込み: {len(rows)} 件")

    report_per_person(rows)
    report_subject_matrix(rows)
    report_per_subject(rows)
    report_overall_ranking(rows)

    print("\n分析完了。\n")


if __name__ == "__main__":
    main()
