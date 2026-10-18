# 1. 選擇基底映像檔 (Base Image)
# 就像選擇作業系統，我們選 Python 3.10 的輕量版 (slim)
FROM python:3.10-slim

# 2. 設定工作目錄
# 告訴 Docker：「接下來的操作都在容器裡的 /app 資料夾進行」
WORKDIR /app

# 3. 安裝系統層級的依賴 (可選，但建議加)
# 為了確保資料庫驅動 (如 psycopg2) 能順利安裝，我們先裝一些 Linux 工具
# - gcc: 編譯器
# - libpq-dev: PostgreSQL 的開發函式庫
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 4. 複製需求清單
# 為什麼不一次複製所有程式碼？因為 Docker 有「快取」機制。
# 只要 requirements.txt 沒變，Docker 就不會重新執行 pip install，這樣建置速度會超快。
COPY requirements.txt .

# 5. 安裝 Python 套件
# --no-cache-dir 是為了減少映像檔體積
RUN pip install --no-cache-dir -r requirements.txt

# 6. 複製所有程式碼
# 把您本機當前目錄 (.) 的所有東西，複製到容器的工作目錄 (.)
COPY . .

# 7. 告訴 Docker 啟動時要執行什麼指令
# 0.0.0.0 是關鍵！這代表允許外部連線 (如果不加，只能在容器內部連線)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]