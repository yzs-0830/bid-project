# database.py 
import databases
import sqlalchemy
import os
from redis import asyncio as aioredis

# --------------------------
# 1. PostgreSQL 設定
# --------------------------

# 優先讀取環境變數 (Docker 用)，如果讀不到才用預設值 (本機開發用)
DEFAULT_URL = "postgresql://postgres:0830allan@localhost:5432/bid_system"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_URL)

database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()

# --------------------------
# 2. 資料表定義
# --------------------------

# 會員表 (Members Table)
members_table = sqlalchemy.Table(
    "members",
    metadata,
    sqlalchemy.Column("user_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("weight", sqlalchemy.Integer, default=0), # 會員權重 W
    sqlalchemy.Column("wins", sqlalchemy.Integer, default=0),   # 得標次數 (同步 weight)
)

# 商品/競標配置表 (Products Table)
products_table = sqlalchemy.Table(
    "products",
    metadata,
    sqlalchemy.Column("product_id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("name", sqlalchemy.String),
    sqlalchemy.Column("base_price", sqlalchemy.Float),
    sqlalchemy.Column("total_quantity", sqlalchemy.Integer), # 庫存 K
    sqlalchemy.Column("duration_minutes", sqlalchemy.Integer),
    sqlalchemy.Column("alpha", sqlalchemy.Float, default=1), # 積分權重 α
    sqlalchemy.Column("beta", sqlalchemy.Float, default=0),  # 積分權重 β
    sqlalchemy.Column("gamma", sqlalchemy.Float, default=0), # 積分權重 γ
    sqlalchemy.Column("start_time", sqlalchemy.BigInteger, default=0), # 毫秒時間戳記
    sqlalchemy.Column("period", sqlalchemy.BigInteger, default=0),     # 毫秒持續時間
    sqlalchemy.Column("settled", sqlalchemy.Boolean, default=False),
)


# 得標紀錄表 (Winners Table)
winners_table = sqlalchemy.Table(
    "winners",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("product_id", sqlalchemy.Integer), # 關聯到 products
    sqlalchemy.Column("user_id", sqlalchemy.String),     # 關聯到 members
    sqlalchemy.Column("win_price", sqlalchemy.Integer),  # 記錄得標價格
    sqlalchemy.Column("win_score", sqlalchemy.Float),    # 記錄得標分數
    sqlalchemy.Column("settled_time", sqlalchemy.BigInteger), # 結算時間
)

# --------------------------
# 3. 建表工具函式
# --------------------------
def create_db_tables():
    """建立所有資料表 (請手動執行此檔案)"""
    print(f"Connecting to database at: {DATABASE_URL}...")
    try:
        engine = sqlalchemy.create_engine(DATABASE_URL)
        metadata.create_all(engine)
        print("✅ 資料表創建成功！(members, products, bids, winners)")
    except Exception as e:
        print(f"❌ 資料表創建失敗: {e}")

# 只有當直接執行 `python database.py` 時才會建立資料表
if __name__ == "__main__":
    create_db_tables()

# --------------------------
# 4. Redis 設定
# --------------------------

# 讀取環境變數 REDIS_URL (來自 docker-compose.yml)
# 若無環境變數，預設連線到本機 Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# 建立非同步 Redis 連線池
redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)