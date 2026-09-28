"use client";

import { useMemo, useState } from "react";
import BottomNav from "@/components/BottomNav";
import {
  CONDITION_CHOICES,
  DESCRIPTION_MAX_LENGTH,
  GENRE_CHOICES,
  SEASON_CHOICES,
  STYLE_CHOICES,
  TITLE_MAX_LENGTH,
} from "@/lib/types";
import { hasAddOneVintageTag, parseGptJson } from "@/lib/validation";

interface FormState {
  title: string;
  genre: string;
  style: string;
  brand: string;
  sale_price: string;
  condition: string;
  season: string;
  storage_location: string;
  description: string;
}

const EMPTY_FORM: FormState = {
  title: "",
  genre: GENRE_CHOICES[0],
  style: STYLE_CHOICES[0],
  brand: "",
  sale_price: "",
  condition: CONDITION_CHOICES[0],
  season: SEASON_CHOICES[0],
  storage_location: "",
  description: "",
};

type SaveState = "idle" | "saving" | "uploading" | "done" | "error";

export default function NewItemPage() {
  const [rawText, setRawText] = useState("");
  const [parseErrors, setParseErrors] = useState<string[]>([]);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [parsed, setParsed] = useState(false);
  const [photos, setPhotos] = useState<File[]>([]);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState<{ done: number; total: number } | null>(null);
  const [clipboardError, setClipboardError] = useState<string | null>(null);
  const [clipboardReading, setClipboardReading] = useState(false);

  const photoPreviewUrls = useMemo(() => photos.map((p) => URL.createObjectURL(p)), [photos]);

  // テキストを直接引数で受け取れるようにし、クリップボード読み込み直後にも
  // (setRawTextの反映を待たず)そのまま解析できるようにする。
  function parseAndApply(text: string): boolean {
    const result = parseGptJson(text);
    if (!result.ok) {
      setParseErrors(result.errors);
      setParsed(false);
      return false;
    }
    const data = result.data!;
    setForm({
      title: data.title,
      genre: data.genre,
      style: data.style,
      brand: data.brand ?? "",
      sale_price: String(data.sale_price),
      condition: data.condition,
      season: data.season,
      storage_location: data.storage_location, // JSONから自動反映。以降このinputで手動修正可能。
      description: data.description,
    });
    setParseErrors([]);
    setParsed(true);
    return true;
  }

  function handleParse() {
    parseAndApply(rawText);
  }

  async function handlePasteFromClipboard() {
    setClipboardError(null);
    setClipboardReading(true);
    try {
      if (!navigator.clipboard || !navigator.clipboard.readText) {
        throw new Error(
          "このブラウザはクリップボードの読み取りに対応していません。手動で貼り付けてください。"
        );
      }
      const text = await navigator.clipboard.readText();
      if (!text.trim()) {
        throw new Error("クリップボードが空です。GPTの出力をコピーしてから再度お試しください。");
      }
      setRawText(text);
      parseAndApply(text);
    } catch (e) {
      const err = e as DOMException | Error;
      if (err.name === "NotAllowedError") {
        setClipboardError(
          "クリップボードへのアクセスが許可されていません。ブラウザの権限設定を確認するか、手動で貼り付けてください。"
        );
      } else {
        setClipboardError(err.message || "クリップボードの読み取りに失敗しました。");
      }
    } finally {
      setClipboardReading(false);
    }
  }

  function handlePhotoSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || []);
    setPhotos((prev) => [...prev, ...files]);
    e.target.value = "";
  }

  function removePhoto(index: number) {
    setPhotos((prev) => prev.filter((_, i) => i !== index));
  }

  function resetForm() {
    setRawText("");
    setForm(EMPTY_FORM);
    setParsed(false);
    setParseErrors([]);
    setPhotos([]);
    setSaveState("idle");
    setSaveError(null);
    setUploadProgress(null);
    setClipboardError(null);
  }

  async function handleSave() {
    setSaveState("saving");
    setSaveError(null);
    try {
      const res = await fetch("/api/items", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: form.title,
          genre: form.genre,
          style: form.style,
          brand: form.brand || null,
          sale_price: Number(form.sale_price),
          condition: form.condition,
          season: form.season,
          storage_location: form.storage_location,
          description: form.description,
          raw_gpt_text: rawText,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || "保存に失敗しました");
      }
      const { item } = await res.json();

      if (photos.length > 0) {
        setSaveState("uploading");
        setUploadProgress({ done: 0, total: photos.length });
        for (let i = 0; i < photos.length; i++) {
          const fd = new FormData();
          fd.append("file", photos[i]!);
          const uploadRes = await fetch(`/api/items/${item.id}/photos`, {
            method: "POST",
            credentials: "include",
            body: fd,
          });
          if (!uploadRes.ok) {
            const body = await uploadRes.json().catch(() => ({}));
            throw new Error(`写真のアップロードに失敗しました(${i + 1}枚目): ${body.error || ""}`);
          }
          setUploadProgress({ done: i + 1, total: photos.length });
        }
      }

      setSaveState("done");
      // 次の商品をすぐ登録できるよう、成功表示後にフォームをクリアして①画面に留まる。
      setTimeout(resetForm, 1200);
    } catch (e) {
      setSaveState("error");
      setSaveError((e as Error).message);
    }
  }

  const titleOverLimit = form.title.length > TITLE_MAX_LENGTH;
  const descriptionOverLimit = form.description.length > DESCRIPTION_MAX_LENGTH;
  const tagMissing = parsed && !hasAddOneVintageTag(form.description);
  const isSaving = saveState === "saving" || saveState === "uploading";

  return (
    <main className="page">
      <h1 style={{ fontSize: 18, marginBottom: 12 }}>① 出品待ち保存</h1>

      <div className="btn-row" style={{ marginBottom: 12 }}>
        <button className="btn btn-primary" onClick={handlePasteFromClipboard} disabled={clipboardReading}>
          {clipboardReading ? "読み込み中..." : "クリップボードから読み込む"}
        </button>
      </div>
      {clipboardError && (
        <div className="warning-box" style={{ borderColor: "var(--danger)" }}>
          {clipboardError}
        </div>
      )}

      <div className="field">
        <label>GPT出力JSONを貼り付け(クリップボード読み込みが使えない場合は手動で貼り付け)</label>
        <textarea
          rows={8}
          value={rawText}
          onChange={(e) => setRawText(e.target.value)}
          placeholder='{"title": "...", "genre": "...", ...}'
        />
      </div>
      <button className="btn" style={{ marginBottom: 16 }} onClick={handleParse} disabled={!rawText.trim()}>
        内容を解析して表示
      </button>

      {parseErrors.length > 0 && (
        <div className="warning-box">
          <strong>JSONを読み取れませんでした:</strong>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
            {parseErrors.map((err, i) => (
              <li key={i}>{err}</li>
            ))}
          </ul>
        </div>
      )}

      {parsed && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="field">
            <label>商品名</label>
            <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            <div className={`char-count ${titleOverLimit ? "over" : ""}`}>
              {form.title.length} / {TITLE_MAX_LENGTH}文字{titleOverLimit ? "(超過。Sheets登録前に修正してください)" : ""}
            </div>
          </div>

          <div className="field">
            <label>ジャンル</label>
            <select value={form.genre} onChange={(e) => setForm({ ...form, genre: e.target.value })}>
              {GENRE_CHOICES.map((g) => (
                <option key={g} value={g}>
                  {g}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label>系統</label>
            <select value={form.style} onChange={(e) => setForm({ ...form, style: e.target.value })}>
              {STYLE_CHOICES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label>ブランド(任意)</label>
            <input value={form.brand} onChange={(e) => setForm({ ...form, brand: e.target.value })} />
          </div>

          <div className="field">
            <label>出品価格</label>
            <input
              type="number"
              inputMode="numeric"
              value={form.sale_price}
              onChange={(e) => setForm({ ...form, sale_price: e.target.value })}
            />
          </div>

          <div className="field">
            <label>商品の状態</label>
            <select value={form.condition} onChange={(e) => setForm({ ...form, condition: e.target.value })}>
              {CONDITION_CHOICES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label>季節</label>
            <select value={form.season} onChange={(e) => setForm({ ...form, season: e.target.value })}>
              {SEASON_CHOICES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label>保管場所(JSONから自動反映。必要に応じて修正してください)</label>
            <input
              value={form.storage_location}
              onChange={(e) => setForm({ ...form, storage_location: e.target.value })}
            />
          </div>

          <div className="field">
            <label>商品説明</label>
            <textarea
              rows={6}
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
            <div className={`char-count ${descriptionOverLimit ? "over" : ""}`}>
              {form.description.length} / {DESCRIPTION_MAX_LENGTH}文字
              {descriptionOverLimit ? "(超過。Sheets登録前に修正してください)" : ""}
            </div>
          </div>

          {tagMissing && (
            <div className="warning-box">#AddOneVintage が商品説明に含まれていません(Sheets登録前に確認してください)</div>
          )}

          <div className="field">
            <label>商品写真(複数選択可)</label>
            <input type="file" accept="image/*" multiple capture="environment" onChange={handlePhotoSelect} />
          </div>
          {photos.length > 0 && (
            <div className="photo-grid">
              {photoPreviewUrls.map((url, i) => (
                <div key={url} style={{ position: "relative" }}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={url} alt={`写真${i + 1}`} />
                  <button
                    className="btn"
                    style={{ position: "absolute", top: 2, right: 2, width: 24, height: 24, padding: 0, minHeight: 0 }}
                    onClick={() => removePhoto(i)}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}

          <button className="btn btn-primary" onClick={handleSave} disabled={isSaving}>
            {saveState === "saving" && "保存中..."}
            {saveState === "uploading" && `写真アップロード中 (${uploadProgress?.done}/${uploadProgress?.total})`}
            {saveState === "done" && "保存しました"}
            {(saveState === "idle" || saveState === "error") && "出品待ちに保存"}
          </button>
          {saveError && <p className="error-text" style={{ marginTop: 8 }}>{saveError}</p>}
        </div>
      )}

      <BottomNav />
    </main>
  );
}
