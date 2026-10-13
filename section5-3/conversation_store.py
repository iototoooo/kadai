"""LINE userId ごとの Dify conversation_id の保存先。

現状は会話履歴を保存せず、毎回新規会話として扱う。
将来 Firestore に置き換える場合は、この2関数の中身だけを差し替えればよい。
  例: collection("line_users").document(user_id) に {"conversation_id": ...} を保存
"""


async def get_conversation_id(user_id: str) -> str:
    """user_id に紐づく conversation_id を返す。未保存なら空文字（= 新規会話）。"""
    return ""


async def save_conversation_id(user_id: str, conversation_id: str) -> None:
    """user_id に conversation_id を紐づけて保存する。現状は何もしない。"""
    return None
