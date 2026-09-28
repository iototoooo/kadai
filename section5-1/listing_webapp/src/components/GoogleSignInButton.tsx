"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { signInWithPopup } from "firebase/auth";
import { getClientAuth, newGoogleProvider } from "@/lib/firebaseClient";

export default function GoogleSignInButton() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSignIn() {
    setError(null);
    setLoading(true);
    try {
      const auth = getClientAuth();
      const result = await signInWithPopup(auth, newGoogleProvider());
      const idToken = await result.user.getIdToken();

      const res = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idToken }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body.error || "ログインに失敗しました");
        await auth.signOut();
        return;
      }

      const next = searchParams.get("next") || "/new";
      router.replace(next);
      router.refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <button className="btn btn-primary" onClick={handleSignIn} disabled={loading}>
        {loading ? "ログイン中..." : "Googleでログイン"}
      </button>
      {error && <p className="error-text" style={{ marginTop: 8 }}>{error}</p>}
    </div>
  );
}
