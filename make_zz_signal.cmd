@echo off
cd /d "%~dp0"
set "PY=%CD%\.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo [ERR] Python venv not found: %PY%
  pause
  exit /b 2
)

"%PY%" -c "import json, os; from datetime import datetime, timezone; os.makedirs('signals', exist_ok=True); ts=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z'); d={'signal_id':'zz-auto-001','ts_utc':ts,'symbol':'AAPL','asset_class':'stock','side':'BUY','entry_type':'limit','entry':190.0,'stop':188.0,'take':194.0,'time_in_force':'DAY','p_win_raw':0.95,'risk_pct_equity_max':0.005,'snapshot_hash':'zz_auto_001'}; open(os.path.join('signals','zz_auto_signal.json'),'w',encoding='utf-8').write(json.dumps(d,ensure_ascii=False,indent=2)); print('OK -> signals\\\\zz_auto_signal.json')"
pause
