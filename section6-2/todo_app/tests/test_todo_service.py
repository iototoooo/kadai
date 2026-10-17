import datetime

import pytest
from pydantic import ValidationError

from todo_app import sheets_client
from todo_app.models import NotificationSettings, TodoInput
from todo_app.sheets_client import HEADER_ROW, HEADER_ROW_V1
from todo_app.tests.fakes import FakeClock, FakeSheetsClient, FakeSpreadsheet, FakeWorksheet, SequentialIds
from todo_app.todo_service import TodoNotFoundError, TodoService

NOW = datetime.datetime(2026, 10, 17, 9, 30, 15)


@pytest.fixture
def ws():
    return FakeWorksheet()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def sheets(ws):
    return FakeSheetsClient(ws)


@pytest.fixture
def service(sheets, clock):
    return TodoService(sheets=sheets, now=clock, new_id=SequentialIds())


# --- 登録・編集・一覧(課題1から継続) ---


def test_create_appends_row_with_all_columns(service, ws):
    todo = service.create_todo(TodoInput(title=" 買い物 ", content="牛乳と卵", due_date="2026-10-20"))

    assert todo.id == f"{1:032x}"
    assert todo.title == "買い物"
    assert ws.rows[1] == [
        todo.id, "買い物", "牛乳と卵", "2026-10-20", "2026-10-16 10:00:00", "2026-10-16 10:00:00",
        "中", "未完了", "", "", "",
    ]
    assert [c[:2] for c in ws.calls] == [("append_row", "RAW")]


def test_create_without_due_date(service, ws):
    todo = service.create_todo(TodoInput(title="いつか"))
    assert todo.due_date == ""
    assert ws.rows[1][3] == ""


def test_formula_like_input_is_written_raw(service, ws):
    service.create_todo(TodoInput(title="=IMPORTXML(\"http://example.invalid\",\"//a\")"))
    assert ws.rows[1][1].startswith("=")
    assert all(c[1] == "RAW" for c in ws.calls)


def test_update_changes_fields_and_updated_at_only(service, ws, clock):
    created = service.create_todo(TodoInput(title="元", content="元の内容", due_date="2026-10-20"))
    service.create_todo(TodoInput(title="別のTodo"))
    # 完了状態・通知記録が入っている行でも、編集で巻き込んで上書きしないこと
    ws.rows[1][7:11] = ["完了", "2026-10-16 12:00:00", "2026-10-20", "2026-10-20"]
    clock.value = "2026-10-17 09:30:00"

    updated = service.update_todo(
        created.id, TodoInput(title="変更後", content="", due_date="2026-11-01", importance="高")
    )

    assert updated.id == created.id
    assert updated.created_at == "2026-10-16 10:00:00"
    assert updated.updated_at == "2026-10-17 09:30:00"
    assert ws.rows[1] == [
        created.id, "変更後", "", "2026-11-01", "2026-10-16 10:00:00", "2026-10-17 09:30:00",
        "高", "完了", "2026-10-16 12:00:00", "2026-10-20", "2026-10-20",
    ]
    assert ws.rows[2][1] == "別のTodo"  # 他の行は変わらない
    assert {c[2] for c in ws.calls if c[0] == "batch_update"} == {"B2:D2", "F2:G2"}
    assert all(c[1] == "RAW" for c in ws.calls)


def test_update_unknown_id_raises(service):
    with pytest.raises(TodoNotFoundError):
        service.update_todo("f" * 32, TodoInput(title="x"))


def test_get_todo(service):
    created = service.create_todo(TodoInput(title="取得テスト"))
    assert service.get_todo(created.id) == created
    with pytest.raises(TodoNotFoundError):
        service.get_todo("0" * 32)


def test_list_sorted_by_due_date_then_newest_and_skips_blank_rows(service, ws, clock):
    clock.value = "2026-10-16 10:00:00"
    a = service.create_todo(TodoInput(title="期日なし"))
    b = service.create_todo(TodoInput(title="遅い期日", due_date="2026-12-01"))
    clock.value = "2026-10-16 11:00:00"
    c = service.create_todo(TodoInput(title="早い期日・古い", due_date="2026-10-18"))
    clock.value = "2026-10-16 12:00:00"
    d = service.create_todo(TodoInput(title="早い期日・新しい", due_date="2026-10-18"))
    ws.rows.append(["", "", "", "", "", ""])  # 手動編集などでできた空行

    assert [t.id for t in service.list_todos()] == [d.id, c.id, b.id, a.id]


def test_list_empty(service):
    assert service.list_todos() == []


def test_list_handles_short_rows(ws, clock):
    ws.rows.append(["abc", "列が足りない行"])
    service = TodoService(sheets=FakeSheetsClient(ws), now=clock)
    [todo] = service.list_todos()
    assert todo.title == "列が足りない行"
    assert todo.updated_at == ""


@pytest.mark.parametrize(
    "kwargs",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "a" * 101},
        {"title": "ok", "content": "a" * 2001},
        {"title": "ok", "due_date": "2026/10/16"},
        {"title": "ok", "due_date": "2026-02-30"},
        {"title": "ok", "importance": "最高"},
    ],
)
def test_invalid_input_rejected(kwargs):
    with pytest.raises(ValidationError):
        TodoInput(**kwargs)


# --- ① 重要度・並び替え ---


def test_v1_rows_default_to_medium_importance_and_open(ws, clock):
    ws.rows.append(["a" * 32, "旧形式の行", "内容", "2026-10-20", "2026-10-01 00:00:00", "2026-10-01 00:00:00"])
    [todo] = TodoService(sheets=FakeSheetsClient(ws), now=clock).list_todos()
    assert todo.importance == "中"
    assert todo.completed is False


def test_unknown_importance_value_falls_back_to_medium(ws, clock):
    ws.rows.append(["a" * 32, "手入力", "", "", "", "", "とても高い", "", "", "", ""])
    [todo] = TodoService(sheets=FakeSheetsClient(ws), now=clock).list_todos()
    assert todo.importance == "中"


def test_sort_by_importance_then_due(service, clock):
    low = service.create_todo(TodoInput(title="低・近い", due_date="2026-10-18", importance="低"))
    mid_far = service.create_todo(TodoInput(title="中・遠い", due_date="2026-12-01"))
    mid_near = service.create_todo(TodoInput(title="中・近い", due_date="2026-10-19"))
    high_none = service.create_todo(TodoInput(title="高・期日なし", importance="高"))
    high_near = service.create_todo(TodoInput(title="高・近い", due_date="2026-10-20", importance="高"))

    ids = [t.id for t in service.list_todos(sort="importance")]
    assert ids == [high_near.id, high_none.id, mid_near.id, mid_far.id, low.id]


def test_sort_by_due_uses_importance_as_tiebreaker(service):
    low = service.create_todo(TodoInput(title="低", due_date="2026-10-18", importance="低"))
    high = service.create_todo(TodoInput(title="高", due_date="2026-10-18", importance="高"))
    later = service.create_todo(TodoInput(title="後", due_date="2026-10-19", importance="高"))
    assert [t.id for t in service.list_todos(sort="due")] == [high.id, low.id, later.id]


# --- ③ 完了チェック・絞り込み ---


def test_set_completion_writes_only_status_columns(service, ws, clock):
    todo = service.create_todo(TodoInput(title="完了させる", due_date="2026-10-20"))
    before = list(ws.rows[1])
    clock.value = "2026-10-17 08:00:00"

    done = service.set_completion(todo.id, True)

    assert done.completed and done.completed_at == "2026-10-17 08:00:00"
    assert ws.rows[1][7:9] == ["完了", "2026-10-17 08:00:00"]
    assert ws.rows[1][5] == "2026-10-17 08:00:00"  # 更新日時
    assert ws.rows[1][:5] == before[:5] and ws.rows[1][6] == before[6] and ws.rows[1][9:] == before[9:]
    assert {c[2] for c in ws.calls if c[0] == "batch_update"} == {"F2", "H2:I2"}

    undone = service.set_completion(todo.id, False)
    assert not undone.completed
    assert ws.rows[1][7:9] == ["未完了", ""]


def test_set_completion_unknown_id(service):
    with pytest.raises(TodoNotFoundError):
        service.set_completion("e" * 32, True)


def test_status_filter(service):
    open_todo = service.create_todo(TodoInput(title="未完了"))
    done_todo = service.create_todo(TodoInput(title="完了"))
    service.set_completion(done_todo.id, True)

    assert [t.id for t in service.list_todos(status="open")] == [open_todo.id]
    assert [t.id for t in service.list_todos(status="done")] == [done_todo.id]
    assert {t.id for t in service.list_todos(status="all")} == {open_todo.id, done_todo.id}


def test_mark_notified_writes_single_cell(service, ws):
    todo = service.create_todo(TodoInput(title="通知", due_date="2026-10-18"))
    service.mark_notified(todo.id, "day_before", "2026-10-18")
    service.mark_notified(todo.id, "same_day", "2026-10-18")
    assert ws.rows[1][9:11] == ["2026-10-18", "2026-10-18"]
    assert [c[2] for c in ws.calls if c[0] == "update"] == ["J2", "K2"]


# --- 通知設定 ---


def test_settings_defaults_from_new_sheet(service):
    assert service.get_settings() == NotificationSettings(
        day_before_enabled=True, day_before_hour=20, same_day_enabled=True, same_day_hour=8
    )


def test_settings_save_and_reload(service, sheets):
    saved = NotificationSettings(day_before_enabled=False, day_before_hour=21, same_day_enabled=True, same_day_hour=7)
    service.save_settings(saved)
    assert service.get_settings() == saved
    assert sheets.settings_worksheet.rows[1][:2] == ["day_before_enabled", "FALSE"]


def test_settings_invalid_or_missing_values_fall_back_to_defaults(ws, clock):
    settings_ws = FakeWorksheet(header=["項目", "値", "説明"], title="設定")
    settings_ws.rows += [["day_before_hour", "99"], ["same_day_hour", "abc"], ["same_day_enabled", "false"]]
    service = TodoService(sheets=FakeSheetsClient(ws, settings_ws), now=clock)
    s = service.get_settings()
    assert (s.day_before_hour, s.same_day_hour, s.same_day_enabled, s.day_before_enabled) == (20, 8, False, True)


@pytest.mark.parametrize("hour", [-1, 24])
def test_settings_hour_validation(hour):
    with pytest.raises(ValidationError):
        NotificationSettings(day_before_hour=hour)


# --- シートの初期化・旧形式からの移行(既存データ保護) ---


def _v1_sheet_with_data():
    ws = FakeWorksheet(header=list(HEADER_ROW_V1))
    ws.rows.append(["b1f075ef188d42f98d41d42a53be4f5c", "既存Todo", "内容", "2026-10-20",
                    "2026-10-16 21:00:00", "2026-10-16 21:05:00"])
    ws.rows.append(["c" * 32, "=SUM(1,2)", "", "", "2026-10-16 22:00:00", "2026-10-16 22:00:00"])
    return ws


def test_migration_initializes_empty_sheet():
    ws = FakeWorksheet(header=[])
    assert sheets_client.migrate_todo_sheet(FakeSpreadsheet(ws), ws, NOW) == "initialized"
    assert ws.rows[0] == HEADER_ROW


def test_migration_accepts_current_header():
    ws = FakeWorksheet()
    assert sheets_client.migrate_todo_sheet(FakeSpreadsheet(ws), ws, NOW) == "ok"
    assert ws.calls == []


def test_migration_from_v1_backs_up_then_only_appends_header():
    ws = _v1_sheet_with_data()
    original = [list(r) for r in ws.rows]
    spreadsheet = FakeSpreadsheet(ws)

    assert sheets_client.migrate_todo_sheet(spreadsheet, ws, NOW) == "migrated"

    backup = spreadsheet.sheets["Todo_backup_20261017_093015"]
    assert backup.rows == original  # バックアップは移行前と完全一致
    assert ws.rows[0] == HEADER_ROW
    assert ws.rows[1:] == original[1:]  # データ行は一切変わらない
    assert [c[2] for c in ws.calls] == ["G1:K1"]  # 書き込みはヘッダー追記の1回だけ


def test_migrated_v1_rows_are_readable(clock):
    ws = _v1_sheet_with_data()
    sheets_client.migrate_todo_sheet(FakeSpreadsheet(ws), ws, NOW)
    todos = TodoService(sheets=FakeSheetsClient(ws), now=clock).list_todos(status="all")
    assert {t.title for t in todos} == {"既存Todo", "=SUM(1,2)"}
    assert all(t.importance == "中" and not t.completed for t in todos)


def test_migration_aborts_when_backup_fails():
    ws = _v1_sheet_with_data()
    original = [list(r) for r in ws.rows]
    spreadsheet = FakeSpreadsheet(ws)
    spreadsheet.fail_duplicate_with = RuntimeError("quota")
    with pytest.raises(RuntimeError):
        sheets_client.migrate_todo_sheet(spreadsheet, ws, NOW)
    assert ws.rows == original and ws.calls == []


def test_migration_aborts_when_backup_differs():
    ws = _v1_sheet_with_data()
    original = [list(r) for r in ws.rows]
    spreadsheet = FakeSpreadsheet(ws)
    spreadsheet.corrupt_duplicate = True
    with pytest.raises(sheets_client.SheetsConfigError):
        sheets_client.migrate_todo_sheet(spreadsheet, ws, NOW)
    assert ws.rows == original and ws.calls == []


def test_migration_aborts_when_extra_columns_have_values():
    ws = _v1_sheet_with_data()
    ws.rows[1] = ws.rows[1] + ["手入力メモ"]
    original = [list(r) for r in ws.rows]
    spreadsheet = FakeSpreadsheet(ws)
    with pytest.raises(sheets_client.SheetsConfigError):
        sheets_client.migrate_todo_sheet(spreadsheet, ws, NOW)
    assert ws.rows == original and list(spreadsheet.sheets) == ["Todo"]


def test_migration_refuses_unexpected_header():
    ws = FakeWorksheet(header=["何か別のデータ"])
    with pytest.raises(sheets_client.SheetsConfigError):
        sheets_client.migrate_todo_sheet(FakeSpreadsheet(ws), ws, NOW)
    assert ws.rows[0] == ["何か別のデータ"]  # 上書きしない


def test_migration_refuses_data_without_header():
    ws = FakeWorksheet(header=[])
    ws.rows.append(["x" * 32, "ヘッダーなしのデータ"])
    with pytest.raises(sheets_client.SheetsConfigError):
        sheets_client.migrate_todo_sheet(FakeSpreadsheet(ws), ws, NOW)
    assert ws.calls == []


def test_settings_sheet_created_once_and_not_overwritten():
    ws = FakeWorksheet()
    spreadsheet = FakeSpreadsheet(ws)
    created = sheets_client.ensure_settings_sheet(spreadsheet)
    assert created.rows[0] == sheets_client.SETTINGS_HEADER
    created.rows[2][1] = "21"  # 利用者が変更した値
    again = sheets_client.ensure_settings_sheet(spreadsheet)
    assert again is created and again.rows[2][1] == "21"
