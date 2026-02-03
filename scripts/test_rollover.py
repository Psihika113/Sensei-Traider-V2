# -*- coding: utf-8 -*-
import sqlite3, datetime as dt
from app.logger import setup_logger
from app.sheets import SheetsClient
from app.outbox import Outbox
from app.service import monthly_rollover_and_report
from app.db import connect
from app.dao import DAO

def main():
    logger = setup_logger("logs", "INFO", True)
    conn = connect("data/trader.db")
    dao = DAO(conn)
    outbox = Outbox(conn, logger)
    sheets = SheetsClient(enabled=True, logger=logger, dao=dao,
                          spreadsheet_id="<PUT_SPREADSHEET_ID>", outbox=outbox)
    monthly_rollover_and_report(sheets, None, conn, logger, now=dt.datetime.utcnow())
    print("OK")

if __name__ == "__main__":
    main()
