# 鱼塘管家后端镜像
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    TZ=Asia/Shanghai

# 用 pip 安装 uv（不依赖 ghcr.io，国内网络更稳定；可通过 PIP_INDEX_URL 指定镜像源）
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" "uv>=0.11,<0.12"
WORKDIR /app

# 先装依赖，充分利用构建缓存
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
RUN uv sync --frozen --no-dev

# 可选：浏览器通道（Playwright + Chromium），镜像会增大约 400MB
ARG WITH_BROWSER=false
RUN if [ "$WITH_BROWSER" = "true" ]; then \
      uv pip install --python .venv/bin/python "playwright>=1.45" && \
      .venv/bin/playwright install --with-deps chromium; \
    fi

RUN useradd --create-home --uid 10001 app && mkdir -p /app/data && chown -R app /app/data
USER app

ENV PATH=/app/.venv/bin:$PATH \
    DATA_DIR=/app/data \
    APP_ENV=production

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
