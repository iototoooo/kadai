import csv
import io
import statistics
import sys
from collections import defaultdict
from pathlib import Path

# Windows コンソールの文字コード問題を回避
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


CSV_FILE = "課題2.csv"


# ── データ読み込み ──────────────────────────────────────────────────────────────

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


# ── 表示ユーティリティ ──────────────────────────────────────────────────────────

def section(title):
    bar = "═" * 64
    print(f"\n{bar}")
    print(f"  {title}")
    print(bar)


def divider():
    print("─" * 64)


# ── 各集計レポート ──────────────────────────────────────────────────────────────

def report_per_person(rows):
    """① 参加者別 基本統計（平均・最高・最低）＋得意／苦手科目"""
    section("① 参加者別 スコアサマリー（平均点順）")

    by_person  = defaultdict(list)
    subj_score = defaultdict(dict)   # {名前: {科目: score}}

    for r in rows:
        by_person[r["名前"]].append(r["スコア"])
        subj_score[r["名前"]][r["科目"]] = r["スコア"]

    results = [
        (name, by_person[name], subj_score[name])
        for name in by_person
    ]
    results.sort(key=lambda x: statistics.mean(x[1]), reverse=True)

    divider()
    print(f"{'順位':^4}  {'名前':<8}  {'平均':>6}  {'最高':>5}  {'最低':>5}  {'得意科目(点)':<14}  {'苦手科目(点)'}")
    divider()

    for rank, (name, sc, subj) in enumerate(results, 1):
        best  = max(subj, key=subj.get)
        worst = min(subj, key=subj.get)
        print(
            f"{rank:^4}  {name:<8}  {statistics.mean(sc):>6.1f}  "
            f"{max(sc):>5}  {min(sc):>5}  "
            f"{best+'('+str(subj[best])+')':^14}  "
            f"{worst+'('+str(subj[worst])+')'}"
        )
    divider()


def report_subject_matrix(rows):
    """② 参加者 × 科目 のスコア一覧（マトリクス表）"""
    section("② 参加者 × 科目 スコアマトリクス")

    names    = sorted({r["名前"] for r in rows})
    subjects = sorted({r["科目"] for r in rows})

    score_map = defaultdict(lambda: defaultdict(list))
    for r in rows:
        score_map[r["名前"]][r["科目"]].append(r["スコア"])

    CELL = 6
    divider()
    header = f"{'名前':<8}" + "".join(f"  {s:^{CELL}}" for s in subjects) + f"  {'平均':>6}"
    print(header)
    divider()

    for name in names:
        cells = []
        all_sc = []
        for subj in subjects:
            sc = score_map[name][subj]
            if sc:
                avg = sum(sc) / len(sc)
                cells.append(f"{avg:^{CELL}.0f}")
                all_sc.extend(sc)
            else:
                cells.append(f"{'--':^{CELL}}")
        overall = sum(all_sc) / len(all_sc) if all_sc else 0
        print(f"{name:<8}" + "".join(f"  {c}" for c in cells) + f"  {overall:>6.1f}")

    divider()
    # 科目別列平均
    col_avgs = []
    col_cells = []
    for subj in subjects:
        sc = [r["スコア"] for r in rows if r["科目"] == subj]
        a = sum(sc) / len(sc)
        col_avgs.append(a)
        col_cells.append(f"{a:^{CELL}.1f}")
    print(f"{'科目平均':<8}" + "".join(f"  {c}" for c in col_cells) + f"  {sum(col_avgs)/len(col_avgs):>6.1f}")
    divider()


def report_per_subject(rows):
    """③ 科目別 最高点者／最低点者／平均"""
    section("③ 科目別 最高点者 / 最低点者 / 平均点")

    by_subject = defaultdict(list)
    for r in rows:
        by_subject[r["科目"]].append(r)

    divider()
    print(f"{'科目':<8}  {'平均':>6}  {'中央値':>6}  {'最高':>5} {'最高点者':<8}  {'最低':>5} {'最低点者'}")
    divider()

    for subj in sorted(by_subject):
        entries = by_subject[subj]
        sc = [e["スコア"] for e in entries]
        top    = max(entries, key=lambda e: e["スコア"])
        bottom = min(entries, key=lambda e: e["スコア"])
        print(
            f"{subj:<8}  {statistics.mean(sc):>6.1f}  {statistics.median(sc):>6.1f}  "
            f"{top['スコア']:>5} {top['名前']:<8}  "
            f"{bottom['スコア']:>5} {bottom['名前']}"
        )
    divider()


def report_overall_ranking(rows):
    """④ 総合ランキング TOP3 / BOTTOM3"""
    section("④ 総合ランキング（全スコア平均）")

    by_person = defaultdict(list)
    for r in rows:
        by_person[r["名前"]].append(r["スコア"])

    ranked = sorted(
        [(name, sc) for name, sc in by_person.items()],
        key=lambda x: statistics.mean(x[1]),
        reverse=True,
    )

    medals = ["🥇", "🥈", "🥉"]

    print("\n  ▼ TOP 3")
    divider()
    for i, (name, sc) in enumerate(ranked[:3]):
        print(
            f"  {medals[i]} {i+1}位  {name:<8}  "
            f"平均 {statistics.mean(sc):.1f}点  "
            f"最高 {max(sc)}点 / 最低 {min(sc)}点"
        )

    print("\n  ▼ BOTTOM 3")
    divider()
    for i, (name, sc) in enumerate(ranked[-3:]):
        rank = len(ranked) - 2 + i
        print(
            f"  {rank}位  {name:<8}  "
            f"平均 {statistics.mean(sc):.1f}点  "
            f"最高 {max(sc)}点 / 最低 {min(sc)}点"
        )
    divider()


# ── メイン ─────────────────────────────────────────────────────────────────────

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
