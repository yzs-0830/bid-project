# database.py 
import databases
import sqlalchemy
import os # 🌟 新增

# 🌟 修改這裡：優先讀取環境變數中的 DATABASE_URL，如果沒有才用 localhost (本機開發用)
# Docker Compose 會自動傳入環境變數，所以會連到 'db'
DEFAULT_URL = "postgresql://postgres:0830allan@localhost:5432/bid_system"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_URL)

database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()

# ⚠️ 這裡我們只定義會員表和商品表，出價 Bid 建議用 Redis 處理即時性
#
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
    sqlalchemy.Column("alpha", sqlalchemy.Float, default=3), # 積分權重 α
    sqlalchemy.Column("beta", sqlalchemy.Float, default=5),  # 積分權重 β
    sqlalchemy.Column("gamma", sqlalchemy.Float, default=3), # 積分權重 γ
    sqlalchemy.Column("start_time", sqlalchemy.BigInteger, default=0), # 毫秒時間戳記
    sqlalchemy.Column("period", sqlalchemy.BigInteger, default=0),     # 毫秒持續時間
    sqlalchemy.Column("settled", sqlalchemy.Boolean, default=False),
)

bids_table = sqlalchemy.Table(
    "bids",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("user_id", sqlalchemy.String),
    sqlalchemy.Column("bid_price", sqlalchemy.Integer),
    sqlalchemy.Column("score", sqlalchemy.Float),
    sqlalchemy.Column("timestamp", sqlalchemy.BigInteger),
)

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

# 創建資料表 (首次運行時使用)
#engine = sqlalchemy.create_engine(DATABASE_URL)
#metadata.create_all(engine)