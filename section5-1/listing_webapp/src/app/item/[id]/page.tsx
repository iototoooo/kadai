"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import CopyButton from "@/components/CopyButton";
import {
  CONDITION_CHOICES,
  DESCRIPTION_MAX_LENGTH,
  GENRE_CHOICES,
  Item,
  SEASON_CHOICES,
  STYLE_CHOICES,
  TITLE_MAX_LENGTH,
} from "@/lib/types";
import { evaluateRegistrationEligibility } from "@/lib/validation";

const STATUS_LABEL: Record<Item["status"], string> = {
  draft: "作成中",
  pending: "出品待ち",
  sheet_registered: "シート登録済み",
  listed: "出品済み",
  cancelled: "対象外",
};

const MERCARI_URL = "https://jp.mercari.com/sell";

export default function ItemDetailPage({ params }: { params: { id: string } }) {
  const router = useRouter();
  const [item, setItem] = useState<Item | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState<Partial<Item>>({});
  const [overrideTagWarning, setOverrideTagWarning] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [photoUploading, setPhotoUploading] = useState(false);
  const [photoUploadProgress, setPhotoUploadProgress] = useState<{ done: number; total: number } | null>(null);
  const [photoUploadError, setPhotoUploadError] = useState<string | null>(null);
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  async function load() {
    const res = await fetch(`/api/items/${params.id}`, { credentials: "include" });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setError(body.error || "取得に失敗しました");
      return;
    }
    const body = await res.json();
    setItem(body.item);
    setEditForm(body.item);
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.id]);

  if (error) {
    return (
      <main className="page">
        <p className="error-text">{error}</p>
        <Link href="/queue" className="btn">
          一覧に戻る
        </Link>
      </main>
    );
  }

  if (!item) {
    return (
      <main className="page">
        <p style={{ color: "var(--text-muted)" }}>読み込み中...</p>
      </main>
    );
  }

  const eligibility = evaluateRegistrationEligibility(item, overrideTagWarning);

  async function saveEdit() {
    setBusyAction("edit");
    try {
      const res = await fetch(`/api/items/${params.id}`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: editForm.title,
          genre: editForm.genre,
          style: editForm.style,
          brand: editForm.brand,
          sale_price: Number(editForm.sale_price),
          condition: editForm.condition,
          season: editForm.season,
          storage_location: editForm.storage_location,
          description: editForm.description,
        }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "更新に失敗しました");
      const body = await res.json();
      setItem(body.item);
      setEditing(false);
      setOverrideTagWarning(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyAction(null);
    }
  }

  async function handleRegister() {
    setRegistering(true);
    setRegisterError(null);
    try {
      const res = await fetch(`/api/items/${params.id}/register`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ overrideTagWarning }),
      });
      const body = await res.json();
      if (!res.ok) {
        setRegisterError(body.error || "登録に失敗しました");
        return;
      }
      setItem(body.item);
    } catch (e) {
      setRegisterError((e as Error).message);
    } finally {
      setRegistering(false);
    }
  }

  async function handleMarkListed() {
    setBusyAction("listed");
    try {
      const res = await fetch(`/api/items/${params.id}/status`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "mark_listed" }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "更新に失敗しました");
      const body = await res.json();
      setItem(body.item);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyAction(null);
    }
  }

  async function handleCancel() {
    setBusyAction("cancel");
    setCancelError(null);
    try {
      const res = await fetch(`/api/items/${params.id}/status`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "mark_cancelled" }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "出品待ちから外す処理に失敗しました");
      router.push("/queue");
    } catch (e) {
      setCancelError((e as Error).message);
      setConfirmingCancel(false);
    } finally {
      setBusyAction(null);
    }
  }

  async function handlePhotoFilesSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || []);
    e.target.value = ""; // 同じファイルを連続選択しても再度changeイベントが発火するようにリセット
    if (files.length === 0) return;

    setPhotoUploading(true);
    setPhotoUploadError(null);
    setPhotoUploadProgress({ done: 0, total: files.length });

    try {
      for (let i = 0; i < files.length; i++) {
        const fd = new FormData();
        fd.append("file", files[i]!);
        const res = await fetch(`/api/items/${params.id}/photos`, {
          method: "POST",
          credentials: "include",
          body: fd,
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(`写真のアップロードに失敗しました(${i + 1}/${files.length}枚目): ${body.error || ""}`);
        }
        const body = await res.json();
        setItem(body.item); // 成功のたびに反映し、写真一覧をすぐ更新する
        setPhotoUploadProgress({ done: i + 1, total: files.length });
      }
    } catch (e) {
      setPhotoUploadError((e as Error).message);
    } finally {
      setPhotoUploading(false);
    }
  }

  async function handleNext() {
    setBusyAction("next");
    try {
      const res = await fetch(`/api/items/${params.id}/next`, { credentials: "include" });
      const body = await res.json();
      if (body.nextItemId) {
        router.push(`/item/${body.nextItemId}`);
      } else {
        router.push("/queue");
      }
    } finally {
      setBusyAction(null);
    }
  }

  const photoUrls = item.photo_paths.map((p) => `/api/photos/${item.id}/${p.split("/").pop()}`);

  return (
    <main className="page">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <h1 style={{ fontSize: 18 }}>③ 出品作業</h1>
        <Link href="/queue" style={{ fontSize: 13, color: "var(--text-muted)" }}>
          一覧に戻る
        </Link>
      </div>

      <div style={{ marginBottom: 12 }}>
        <span className={`status-badge status-${item.status}`}>{STATUS_LABEL[item.status]}</span>
        {item.management_number && (
          <span style={{ marginLeft: 8, fontSize: 13, color: "var(--text-muted)" }}>
            管理番号: <strong>{item.management_number}</strong>
          </span>
        )}
      </div>

      {photoUrls.length > 0 ? (
        <div className="photo-grid">
          {photoUrls.map((url) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={url} src={url} alt={item.title} />
          ))}
        </div>
      ) : (
        <p style={{ color: "var(--text-muted)", fontSize: 13 }}>
          写真がありません(出品済みから30日経過後は自動削除されます)
        </p>
      )}

      <div className="field" style={{ marginBottom: 16 }}>
        <label>写真を追加(スマホの写真ライブラリから1枚または複数選択可)</label>
        <input
          type="file"
          accept="image/*"
          multiple
          disabled={photoUploading}
          onChange={handlePhotoFilesSelected}
        />
        {photoUploading && photoUploadProgress && (
          <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
            アップロード中... ({photoUploadProgress.done}/{photoUploadProgress.total})
          </p>
        )}
        {photoUploadError && <p className="error-text">{photoUploadError}</p>}
      </div>

      {!editing ? (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="field">
            <label>商品名</label>
            <p>{item.title}</p>
          </div>
          <div className="field">
            <label>商品説明</label>
            <p style={{ whiteSpace: "pre-wrap" }}>{item.description}</p>
          </div>
          <div className="field">
            <label>出品価格</label>
            <p>¥{item.sale_price.toLocaleString()}</p>
          </div>
          <div className="field">
            <label>保管場所</label>
            <p>{item.storage_location}</p>
          </div>
          <button className="btn" onClick={() => setEditing(true)}>
            編集
          </button>
        </div>
      ) : (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="field">
            <label>商品名</label>
            <input value={editForm.title ?? ""} onChange={(e) => setEditForm({ ...editForm, title: e.target.value })} />
            <div className={`char-count ${(editForm.title?.length ?? 0) > TITLE_MAX_LENGTH ? "over" : ""}`}>
              {editForm.title?.length ?? 0} / {TITLE_MAX_LENGTH}文字
            </div>
          </div>
          <div className="field">
            <label>ジャンル</label>
            <select value={editForm.genre ?? ""} onChange={(e) => setEditForm({ ...editForm, genre: e.target.value })}>
              {GENRE_CHOICES.map((g) => (
                <option key={g} value={g}>
                  {g}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>系統</label>
            <select value={editForm.style ?? ""} onChange={(e) => setEditForm({ ...editForm, style: e.target.value })}>
              {STYLE_CHOICES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>ブランド</label>
            <input value={editForm.brand ?? ""} onChange={(e) => setEditForm({ ...editForm, brand: e.target.value })} />
          </div>
          <div className="field">
            <label>出品価格</label>
            <input
              type="number"
              value={editForm.sale_price ?? 0}
              onChange={(e) => setEditForm({ ...editForm, sale_price: Number(e.target.value) })}
            />
          </div>
          <div className="field">
            <label>商品の状態</label>
            <select value={editForm.condition ?? ""} onChange={(e) => setEditForm({ ...editForm, condition: e.target.value })}>
              {CONDITION_CHOICES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>季節</label>
            <select value={editForm.season ?? ""} onChange={(e) => setEditForm({ ...editForm, season: e.target.value })}>
              {SEASON_CHOICES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>保管場所</label>
            <input
              value={editForm.storage_location ?? ""}
              onChange={(e) => setEditForm({ ...editForm, storage_location: e.target.value })}
            />
          </div>
          <div className="field">
            <label>商品説明</label>
            <textarea
              rows={6}
              value={editForm.description ?? ""}
              onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
            />
            <div className={`char-count ${(editForm.description?.length ?? 0) > DESCRIPTION_MAX_LENGTH ? "over" : ""}`}>
              {editForm.description?.length ?? 0} / {DESCRIPTION_MAX_LENGTH}文字
            </div>
          </div>
          <div className="btn-row">
            <button className="btn" onClick={() => { setEditing(false); setEditForm(item); }}>
              キャンセル
            </button>
            <button className="btn btn-primary" onClick={saveEdit} disabled={busyAction === "edit"}>
              保存
            </button>
          </div>
        </div>
      )}

      <div className="btn-row" style={{ marginBottom: 12 }}>
        <CopyButton label="商品名コピー" text={item.title} />
        <CopyButton label="価格コピー" text={String(item.sale_price)} />
      </div>
      <div style={{ marginBottom: 16 }}>
        <CopyButton label="商品説明コピー" text={item.description} />
      </div>

      {item.status === "pending" && (
        <div style={{ marginBottom: 16 }}>
          {eligibility.hardBlockReasons.map((r) => (
            <div key={r} className="warning-box" style={{ borderColor: "var(--danger)" }}>
              {r}
            </div>
          ))}
          {eligibility.overridableReasons.map((r) => (
            <div key={r} className="warning-box">
              {r}
              {!overrideTagWarning && (
                <div style={{ marginTop: 6 }}>
                  <button className="btn" onClick={() => setOverrideTagWarning(true)}>
                    警告を確認して登録する
                  </button>
                </div>
              )}
            </div>
          ))}
          <button
            className="btn btn-primary"
            onClick={handleRegister}
            disabled={!eligibility.canRegister || registering}
          >
            {registering ? "登録中..." : "Google Sheetsへ登録"}
          </button>
          {registerError && <p className="error-text" style={{ marginTop: 8 }}>{registerError}</p>}
        </div>
      )}

      {item.status === "sheet_registered" && (
        <div className="btn-row" style={{ marginBottom: 16 }}>
          <a className="btn" href={MERCARI_URL} target="_blank" rel="noreferrer">
            メルカリを開く
          </a>
          <button className="btn btn-primary" onClick={handleMarkListed} disabled={busyAction === "listed"}>
            出品済みにする
          </button>
        </div>
      )}

      {(item.status === "draft" || item.status === "pending") && (
        <div style={{ marginBottom: 16 }}>
          {!confirmingCancel ? (
            <button className="btn" onClick={() => setConfirmingCancel(true)} disabled={busyAction === "cancel"}>
              出品待ちから外す
            </button>
          ) : (
            <div className="warning-box">
              本当に出品待ちから外しますか？(取り消せません。写真は既存の30日後自動削除ルールの対象になります)
              <div className="btn-row" style={{ marginTop: 8 }}>
                <button className="btn" onClick={() => setConfirmingCancel(false)} disabled={busyAction === "cancel"}>
                  キャンセル
                </button>
                <button className="btn btn-primary" onClick={handleCancel} disabled={busyAction === "cancel"}>
                  {busyAction === "cancel" ? "処理中..." : "はい、外す"}
                </button>
              </div>
            </div>
          )}
          {cancelError && <p className="error-text" style={{ marginTop: 8 }}>{cancelError}</p>}
        </div>
      )}

      <button className="btn" onClick={handleNext} disabled={busyAction === "next"}>
        次の商品へ
      </button>
    </main>
  );
}
