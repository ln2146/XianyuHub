"""本地启动：python -m app（读取 BIND_HOST / APP_PORT）。"""

import uvicorn

from app.core.config import get_settings


def main() -> None:
    s = get_settings()
    uvicorn.run("app.main:app", host=s.bind_host, port=s.app_port, proxy_headers=True)


if __name__ == "__main__":
    main()
