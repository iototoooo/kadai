import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SERVICE_ACCOUNT_FILE = "service_account.json"
SPREADSHEET_ID = "1xpDblB4BIuwsyV9Wh_7cMpQcSOoKx5yJQoyfziuxHWc"


def get_worksheet(spreadsheet_id: str = SPREADSHEET_ID, sheet_index: int = 0):
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES,
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(spreadsheet_id)
    return spreadsheet.get_worksheet(sheet_index)


def write_sample_data():
    worksheet = get_worksheet()

    data = [
        ["名前", "年齢", "メール"],
        ["田中太郎", 30, "tanaka@example.com"],
        ["鈴木花子", 25, "suzuki@example.com"],
    ]
    worksheet.update(data, "A1")
    worksheet.append_row(["山田一郎", 28, "yamada@example.com"])

    print("データの書き込みが完了しました")


if __name__ == "__main__":
    write_sample_data()
