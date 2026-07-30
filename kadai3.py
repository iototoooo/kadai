import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
import japanize_matplotlib  # noqa: F401 — registers Japanese font

matplotlib.rcParams['axes.unicode_minus'] = False

df = pd.read_csv("課題3.csv")
df.columns = df.columns.str.strip()
df["スコア"] = pd.to_numeric(df["スコア"], errors="coerce")

# ── 円グラフ：所属ごとの参加者数 ──────────────────────────────
counts = df["所属"].value_counts()

fig, ax = plt.subplots(figsize=(7, 7))
ax.pie(
    counts,
    labels=counts.index,
    autopct="%1.1f%%",
    startangle=90,
    counterclock=False,
)
ax.set_title("所属ごとの参加者数", fontsize=16, pad=20)
plt.tight_layout()
plt.savefig("pie_chart.png", dpi=150)
plt.close()
print("pie_chart.png を保存しました")

# ── 棒グラフ：所属ごとの平均・最高・最低スコア ───────────────
stats = df.groupby("所属")["スコア"].agg(["mean", "max", "min"]).reset_index()
stats.columns = ["所属", "平均", "最高", "最低"]

x = range(len(stats))
width = 0.25

fig, ax = plt.subplots(figsize=(9, 6))
ax.bar([i - width for i in x], stats["平均"], width=width, label="平均スコア", color="steelblue")
ax.bar([i         for i in x], stats["最高"], width=width, label="最高スコア", color="mediumseagreen")
ax.bar([i + width for i in x], stats["最低"], width=width, label="最低スコア", color="tomato")

ax.set_xticks(list(x))
ax.set_xticklabels(stats["所属"], fontsize=12)
ax.set_xlabel("所属", fontsize=13)
ax.set_ylabel("スコア", fontsize=13)
ax.set_title("所属ごとのスコア（平均・最高・最低）", fontsize=16)
ax.legend(fontsize=11)
ax.set_ylim(0, 110)
ax.yaxis.grid(True, linestyle="--", alpha=0.7)
ax.set_axisbelow(True)
plt.tight_layout()
plt.savefig("bar_chart.png", dpi=150)
plt.close()
print("bar_chart.png を保存しました")

# ── ヒストグラム：全参加者のスコア分布 ───────────────────────
fig, ax = plt.subplots(figsize=(8, 5))
ax.hist(df["スコア"], bins=10, color="steelblue", edgecolor="white", linewidth=0.8)
ax.set_xlabel("スコア", fontsize=13)
ax.set_ylabel("人数", fontsize=13)
ax.set_title("全参加者のスコア分布", fontsize=16)
ax.yaxis.grid(True, linestyle="--", alpha=0.7)
ax.set_axisbelow(True)
plt.tight_layout()
plt.savefig("histogram.png", dpi=150)
plt.close()
print("histogram.png を保存しました")
