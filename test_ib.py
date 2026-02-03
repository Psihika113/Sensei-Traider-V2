# test_ib.py
from app.config import load_app_config
from adapters.ibkr.client import IBKRClient, IBKRConnectionParams


def main() -> None:
    # 1) Читаем конфиг
    cfg = load_app_config("config/app.toml")

    # Пытаемся взять настройки IBKR из конфига.
    # Если в AppConfig поля называются чуть иначе, мы поправим,
    # но базовая идея такая:
    ib_params = IBKRConnectionParams(
        host=getattr(cfg.ibkr, "host", "127.0.0.1"),
        port=getattr(cfg.ibkr, "port", 7497),
        client_id=getattr(cfg.ibkr, "client_id", 1),
    )

    client = IBKRClient(ib_params)

    print("Trying to connect to IBKR...")
    print(f"  host={ib_params.host}, port={ib_params.port}, client_id={ib_params.client_id}")

    try:
        client.connect()
    except Exception as exc:
        print("\n❌ Failed to connect to IBKR")
        print(f"   type: {type(exc).__name__}")
        print(f"   msg : {exc}")
    else:
        print("\n✅ Connected to IBKR successfully.")
        print("   client.is_connected:", client.is_connected)
    finally:
        try:
            client.disconnect()
        except Exception as exc:
            print("\n⚠ Error on disconnect:", exc)


if __name__ == "__main__":
    main()
