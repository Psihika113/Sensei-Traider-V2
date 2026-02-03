# -*- coding: utf-8 -*-
import os
import json
from dotenv import load_dotenv
import gspread
import datetime as dt

def main():
    load_dotenv()
    sa_path = os.getenv("GOOGLE_SA_PATH")
    sheet_id = os.getenv("SPREADSHEET_ID")
    if not sa_path or not sheet_id:
        print("ERROR: GOOGLE_SA_PATH or SPREADSHEET_ID is not set")
        return

    with open(sa_path, "r", encoding="utf-8") as f:
        svc = json.load(f)
    print("Using service account:", svc.get("client_email"))

    gc = gspread.service_account(filename=sa_path)

    try:
        sh = gc.open_by_key(sheet_id)
    except gspread.exceptions.SpreadsheetNotFound:
        print("ERROR: SpreadsheetNotFound (проверь ID в URL и доступ сервисного аккаунта)")
        return

    name = f"Trades_{dt.datetime.utcnow().strftime('%Y%m')}"
    try:
        ws = sh.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows=1000, cols=30)

    # 1) Можно так (надежно):
    ws.update_cell(1, 1, 'trade_id')
    # 2) Или так (строго 2D-матрица):
    # ws.update('A1:A1', [['trade_id']])

    print(f"OK: sheets access, worksheet '{name}' is ready.")

if __name__ == "__main__":
    main()
