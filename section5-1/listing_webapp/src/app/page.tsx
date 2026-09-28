import { redirect } from "next/navigation";

/** ログイン後のデフォルト画面は①保存画面(要件: 記録フェーズを0タップで開始できるようにする)。 */
export default function RootPage() {
  redirect("/new");
}
