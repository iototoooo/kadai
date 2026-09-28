"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function BottomNav() {
  const pathname = usePathname();

  return (
    <nav className="bottom-nav">
      <Link href="/new" className={pathname === "/new" ? "active" : ""}>
        ① 保存
      </Link>
      <Link href="/queue" className={pathname?.startsWith("/queue") || pathname?.startsWith("/item") ? "active" : ""}>
        ② 出品待ち一覧
      </Link>
    </nav>
  );
}
