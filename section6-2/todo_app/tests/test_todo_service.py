import pytest
from pydantic import ValidationError

from todo_app import sheets_client
from todo_app.models import TodoInput
from todo_app.tests.fakes import FakeClock, FakeSheetsClient, FakeWorksheet, SequentialIds
from todo_app.todo_service import TodoNotFoundError, TodoService


@pytest.fixture
def ws():
    return FakeWorksheet()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def service(ws, clock):
    return TodoService(sheets=FakeSheetsClient(ws), now=clock, new_id=SequentialIds())


def test_create_appends_row_with_all_columns(service, ws):
    todo = service.create_todo(TodoInput(title=" 買い物 ", content="牛乳と卵", due_date="2026-10-20"))

    assert todo.id == f"{1:032x}"
    assert todo.title == "買い物"
    assert ws.rows[1] == [todo.id, "買い物", "牛乳と卵", "2026-10-20", "2026-10-16 10:00:00", "2026-10-16 10:00:00"]
    assert ws.calls == [("append_row", "RAW")]


def test_create_without_due_date(service, ws):
    todo = service.create_todo(TodoInput(title="いつか"))
    assert todo.due_date == ""
    assert ws.rows[1][3] == ""


def test_formula_like_input_is_written_raw(service, ws):
    service.create_todo(TodoInput(title="=IMPORTXML(\"http://example.invalid\",\"//a\")"))
    assert ws.rows[1][1].startswith("=")
    assert ws.calls == [("append_row", "RAW")]


def test_update_changes_fields_and_updated_at_only(service, ws, clock):
    created = service.create_todo(TodoInput(title="元", content="元の内容", due_date="2026-10-20"))
    service.create_todo(TodoInput(title="別のTodo"))
    clock.value = "2026-10-17 09:30:00"

    updated = service.update_todo(created.id, TodoInput(title="変更後", content="", due_date="2026-11-01"))

    assert updated.id == created.id
    assert updated.created_at == "2026-10-16 10:00:00"
    assert updated.updated_at == "2026-10-17 09:30:00"
    assert ws.rows[1] == [created.id, "変更後", "", "2026-11-01", "2026-10-16 10:00:00", "2026-10-17 09:30:00"]
    assert ws.rows[2][1] == "別のTodo"  # 他の行は変わらない
    assert ws.calls[-1] == ("update", "RAW")


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
    ],
)
def test_invalid_input_rejected(kwargs):
    with pytest.raises(ValidationError):
        TodoInput(**kwargs)


def test_ensure_header_writes_header_on_empty_sheet():
    ws = FakeWorksheet(header=[])
    sheets_client.ensure_header(ws)
    assert ws.rows[0] == sheets_client.HEADER_ROW
    assert ws.calls == [("update", "RAW")]


def test_ensure_header_accepts_existing_header():
    ws = FakeWorksheet()
    sheets_client.ensure_header(ws)
    assert ws.calls == []


def test_ensure_header_refuses_unexpected_sheet():
    ws = FakeWorksheet(header=["何か別のデータ"])
    with pytest.raises(sheets_client.SheetsConfigError):
        sheets_client.ensure_header(ws)
    assert ws.rows[0] == ["何か別のデータ"]  # 上書きしない
