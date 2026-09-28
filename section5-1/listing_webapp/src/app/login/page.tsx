import { Suspense } from "react";
import GoogleSignInButton from "@/components/GoogleSignInButton";

export default function LoginPage() {
  return (
    <main className="page" style={{ paddingTop: 64 }}>
      <div className="card" style={{ textAlign: "center" }}>
        <h1 style={{ fontSize: 20, marginBottom: 8 }}>出品待ち管理</h1>
        <p style={{ color: "var(--text-muted)", marginBottom: 20 }}>
          許可されたGoogleアカウントでログインしてください。
        </p>
        <Suspense fallback={null}>
          <GoogleSignInButton />
        </Suspense>
      </div>
    </main>
  );
}
