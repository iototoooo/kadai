// 画面共通: API呼び出しとログアウト。未ログイン(401)ならログイン画面へ移動する。
async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    credentials: "same-origin",
  });
  if (res.status === 401) {
    window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname);
    throw new Error("ログインが必要です");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(body.error || "処理に失敗しました");
  }
  return body;
}

const logoutButton = document.getElementById("logout");
if (logoutButton) {
  logoutButton.addEventListener("click", async () => {
    await fetch("/api/session/logout", { method: "POST", credentials: "same-origin" }).catch(() => {});
    window.location.href = "/login";
  });
}
