"""drive_client.py のOAuth資格情報構築・エラー変換・フォルダ/アップロードロジックを
実際のGoogle Drive APIに接続せず検証する。
"""

import json

import pytest
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from expense_manager import config
from expense_manager.drive_client import DriveAuthExpiredError, DriveClient, _build_credentials


class FakeResp:
    def __init__(self, status: int):
        self.status = status
        self.reason = "error"


class FakeRequest:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def execute(self):
        if self._error:
            raise self._error
        return self._result


class FakeFilesResource:
    def __init__(self, list_result=None, list_error=None, create_error=None, create_ids=None):
        self.list_result = list_result if list_result is not None else {"files": []}
        self.list_error = list_error
        self.create_error = create_error
        self._create_ids = list(create_ids) if create_ids else None
        self.create_calls = []
        self.list_calls = []
        self.deleted_ids = []

    def list(self, q=None, fields=None, spaces=None):
        self.list_calls.append(q)
        return FakeRequest(result=self.list_result, error=self.list_error)

    def create(self, body=None, media_body=None, fields=None):
        self.create_calls.append({"body": body, "has_media": media_body is not None})
        if self.create_error:
            return FakeRequest(error=self.create_error)
        if self._create_ids:
            file_id = self._create_ids.pop(0)
        else:
            file_id = f"fake-id-{len(self.create_calls)}"
        return FakeRequest(result={"id": file_id, "webViewLink": f"https://drive.example.invalid/{file_id}"})

    def delete(self, fileId=None):
        self.deleted_ids.append(fileId)
        return FakeRequest(result={})


class FakeDriveService:
    def __init__(self, files_resource: FakeFilesResource):
        self._files = files_resource

    def files(self):
        return self._files


def make_client(files_resource: FakeFilesResource) -> DriveClient:
    # credentials/serviceはテスト用の差し替え口なので、credentialsはダミーで足りる。
    return DriveClient(credentials=object(), service=FakeDriveService(files_resource))


def test_build_credentials_reads_from_env(monkeypatch):
    monkeypatch.setattr(
        config,
        "GOOGLE_DRIVE_OAUTH_JSON",
        json.dumps({"refresh_token": "rt-123", "client_id": "cid-456", "client_secret": "secret-789"}),
    )
    creds = _build_credentials()
    assert creds.refresh_token == "rt-123"
    assert creds.client_id == "cid-456"
    assert creds.client_secret == "secret-789"
    assert creds.scopes == config.DRIVE_OAUTH_SCOPES


def test_build_credentials_raises_when_unset(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_DRIVE_OAUTH_JSON", None)
    with pytest.raises(RuntimeError):
        _build_credentials()


def test_execute_translates_refresh_error_to_drive_auth_expired():
    files = FakeFilesResource(list_error=RefreshError("token revoked"))
    client = make_client(files)
    with pytest.raises(DriveAuthExpiredError):
        client._find_or_create_folder("root-id", "2026")


def test_execute_translates_invalid_grant_http_error_to_drive_auth_expired():
    content = json.dumps({"error": "invalid_grant", "error_description": "Token has been expired or revoked."}).encode()
    error = HttpError(FakeResp(400), content)
    files = FakeFilesResource(list_error=error)
    client = make_client(files)
    with pytest.raises(DriveAuthExpiredError):
        client._find_or_create_folder("root-id", "2026")


def test_execute_reraises_unrelated_http_error():
    content = json.dumps({"error": "somethingElse"}).encode()
    error = HttpError(FakeResp(500), content)
    files = FakeFilesResource(list_error=error)
    client = make_client(files)
    with pytest.raises(HttpError):
        client._find_or_create_folder("root-id", "2026")


def test_find_or_create_folder_creates_when_not_found():
    files = FakeFilesResource(list_result={"files": []}, create_ids=["new-folder-id"])
    client = make_client(files)
    folder_id = client._find_or_create_folder("root-id", "2026")
    assert folder_id == "new-folder-id"
    assert len(files.create_calls) == 1
    assert files.create_calls[0]["body"]["parents"] == ["root-id"]


def test_find_or_create_folder_reuses_existing():
    files = FakeFilesResource(list_result={"files": [{"id": "existing-id", "name": "2026"}]})
    client = make_client(files)
    folder_id = client._find_or_create_folder("root-id", "2026")
    assert folder_id == "existing-id"
    assert len(files.create_calls) == 0  # 新規作成は呼ばれない


def test_create_root_folder_has_no_parent():
    files = FakeFilesResource(create_ids=["root-folder-id"])
    client = make_client(files)
    folder_id, link = client.create_root_folder("経費管理")
    assert folder_id == "root-folder-id"
    assert "parents" not in files.create_calls[0]["body"]


def test_upload_receipt_image_creates_year_month_folders_and_file(monkeypatch):
    files = FakeFilesResource(
        list_result={"files": []},  # 年/月フォルダとも未作成の状態
        create_ids=["year-folder-id", "month-folder-id", "receipt-file-id"],
    )
    monkeypatch.setattr(config, "EXPENSE_DRIVE_ROOT_FOLDER_ID", "root-id")
    client = make_client(files)
    file_id, url = client.upload_receipt_image(
        year="2026",
        month="09",
        management_number="EX2609001",
        file_bytes=b"fake-image-bytes",
        content_type="image/jpeg",
        extension=".jpg",
    )
    assert file_id == "receipt-file-id"
    assert url.endswith("receipt-file-id")
    # 3回create呼ばれる: 年フォルダ, 月フォルダ, ファイル本体
    assert len(files.create_calls) == 3
    final_call = files.create_calls[-1]
    assert final_call["body"]["name"] == "EX2609001.jpg"
    assert final_call["body"]["parents"] == ["month-folder-id"]
    assert final_call["has_media"] is True
