import Link from "next/link";
import type { Item } from "@/lib/types";

const STATUS_LABEL: Record<Item["status"], string> = {
  draft: "作成中",
  pending: "出品待ち",
  sheet_registered: "シート登録済み",
  listed: "出品済み",
  cancelled: "対象外",
};

function formatDateTime(ms: number): string {
  return new Date(ms).toLocaleString("ja-JP", { dateStyle: "short", timeStyle: "short" });
}

export default function ItemCard({ item }: { item: Item }) {
  const thumbPath = item.photo_paths[0];
  const thumbUrl = thumbPath ? `/api/photos/${item.id}/${thumbPath.split("/").pop()}` : null;

  return (
    <Link href={`/item/${item.id}`} className="item-card">
      {thumbUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={thumbUrl} alt={item.title} className="item-card__thumb" />
      ) : (
        <div className="item-card__thumb" />
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {item.title}
        </div>
        <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
          ¥{item.sale_price.toLocaleString()} ・ {item.storage_location}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 6 }}>
          <span className={`status-badge status-${item.status}`}>{STATUS_LABEL[item.status]}</span>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{formatDateTime(item.created_at)}</span>
        </div>
      </div>
    </Link>
  );
}
