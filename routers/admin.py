from fastapi import APIRouter
from pydantic import BaseModel
import time
import sqlalchemy
# 🌟 修改 1: 記得引入 redis_client
from database import database, products_table, redis_client

router = APIRouter()

class ProductConfig(BaseModel):
    name: str
    base_price: float
    total_quantity: int
    duration_minutes: int

class ScoreConfig(BaseModel):
    A: float
    B: float
    C: float

# --------------------------
# 輔助函式
# --------------------------

async def get_latest_product_config():
    """
    從資料庫獲取「最新」商品的詳細配置
    邏輯：依 product_id 倒序排列 (DESC)，取第 1 筆
    """
    query = (
        sqlalchemy.select(products_table)
        .order_by(products_table.c.product_id.desc())
        .limit(1)
    )
    record = await database.fetch_one(query)
    return dict(record) if record else None

# --------------------------
# API 路由
# --------------------------

@router.post("/set_product")
async def set_product(cfg: ProductConfig):
    current_time = int(time.time() * 1000)
    period_ms = cfg.duration_minutes * 60 * 1000

    # 1. 準備寫入的數據
    values = {
        "name": cfg.name,
        "base_price": cfg.base_price,
        "total_quantity": cfg.total_quantity,
        "duration_minutes": cfg.duration_minutes,
        "start_time": current_time,
        "period": period_ms,
        "settled": False,
        "alpha": 3.0,
        "beta": 5.0,
        "gamma": 3.0
    }

    async with database.transaction():
        # 純 INSERT，讓 DB 自動生成新的 product_id
        insert_query = products_table.insert().values(**values)
        await database.execute(insert_query)

    # ---------------------------------------------------------
    # 🔥 修改 2: 強制清除 Redis 的舊商品快取
    # ---------------------------------------------------------
    # 因為 bidding.py 裡的 get_current_product 有 1 小時快取，
    # 這裡必須刪除，讓系統下次讀取時被迫去抓這裡剛寫入的新商品。
    await redis_client.delete("system:current_product")
    print(f"🧹 [Admin] 舊快取已清除，新商品 {cfg.name} 上架中...")

    # 2. 回傳最新配置
    updated_product = await get_latest_product_config()
    
    if updated_product:
        updated_product["bids"] = []
    
    return {"status": "ok", "product": updated_product}


@router.post("/set_score")
async def set_score(cfg: ScoreConfig):
    # 更新「最新」商品的 alpha, beta, gamma
    
    # 1. 先找出最新商品的 ID
    latest_product = await get_latest_product_config()
    
    if not latest_product:
        return {"status": "fail", "message": "請先上架商品後再設定分數"}

    target_id = latest_product["product_id"]

    # 2. 更新該商品的參數
    values = {
        "alpha": cfg.A,
        "beta": cfg.B,
        "gamma": cfg.C
    }

    update_query = (
        sqlalchemy.update(products_table)
        .where(products_table.c.product_id == target_id)
        .values(**values)
    )
    await database.execute(update_query)

    # ---------------------------------------------------------
    # 🔥 修改 3: 修改分數也要清除快取
    # ---------------------------------------------------------
    # 不然前端顯示的預估價公式會用舊係數算，導致顯示錯誤
    await redis_client.delete("system:current_product")
    print(f"🧹 [Admin] 舊快取已清除，新分數參數已套用: {values}")
        
    return {"status": "ok", "score": {"A": cfg.A, "B": cfg.B, "C": cfg.C}}