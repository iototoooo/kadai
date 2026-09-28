"use client";

import { useEffect, useState } from "react";
import BottomNav from "@/components/BottomNav";
import ItemCard from "@/components/ItemCard";
import type { Item, ItemStatus } from "@/lib/types";

const FILTERS: { key: string; label: string; statuses: ItemStatus[] }[] = [
  { key: "pending", label: "出品待ち", statuses: ["pending"] },
  { key: "sheet_registered", label: "シート登録済み", statuses: ["sheet_registered"] },
  { key: "listed", label: "出品済み", statuses: ["listed"] },
  { key: "draft", label: "作成中", statuses: ["draft"] },
  { key: "cancelled", label: "外した商品", statuses: ["cancelled"] },
  // 「すべて」はcancelledを含まない(cancelledは「外した商品」タブでのみ確認する)。
  { key: "all", label: "すべて", statuses: ["draft", "pending", "sheet_registered", "listed"] },
];

export default function QueuePage() {
  const [filterKey, setFilterKey] = useState("pending");
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const filter = FILTERS.find((f) => f.key === filterKey)!;
    const qs = filter.statuses.length > 0 ? `?status=${filter.statuses.join(",")}` : "";
    setItems(null);
    fetch(`/api/items${qs}`, { credentials: "include" })
      .then(async (res) => {
        if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "取得に失敗しました");
        return res.json();
      })
      .then((body) => {
        // 新しい順に表示する(作成日時降順)。
        setItems([...body.items].sort((a: Item, b: Item) => b.created_at - a.created_at));
      })
      .catch((e) => setError(e.message));
  }, [filterKey]);

  return (
    <main className="page">
      <h1 style={{ fontSize: 18, marginBottom: 12 }}>出品待ち一覧</h1>

      <div className="btn-row" style={{ overflowX: "auto", marginBottom: 16, paddingBottom: 4 }}>
        {FILTERS.map((f) => (
          <button
            key={f.key}
            className="btn"
            style={{
              width: "auto",
              whiteSpace: "nowrap",
              background: filterKey === f.key ? "var(--accent)" : undefined,
              color: filterKey === f.key ? "var(--accent-contrast)" : undefined,
              borderColor: filterKey === f.key ? "var(--accent)" : undefined,
            }}
            onClick={() => setFilterKey(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {error && <p className="error-text">{error}</p>}
      {items === null && !error && <p style={{ color: "var(--text-muted)" }}>読み込み中...</p>}
      {items !== null && items.length === 0 && <p style={{ color: "var(--text-muted)" }}>該当する商品がありません</p>}
      {items?.map((item) => <ItemCard key={item.id} item={item} />)}

      <BottomNav />
    </main>
  );
}
