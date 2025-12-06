from fastapi import APIRouter
from pydantic import BaseModel
import time
import sqlalchemy
from database import database, products_table

# bids_table 在這裡已經不需要了，因為我們不再刪除舊紀錄
# from database import bids_table 

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
        # 給定預設參數，防止管理員忘記設定分數時系統出錯
        "alpha": 3.0,
        "beta": 5.0,
        "gamma": 3.0
    }

    async with database.transaction():
        # ⚠️ 修正 1: 移除 bids_table.delete()，保留歷史紀錄
        
        # ⚠️ 修正 2: 改為純 INSERT，讓 DB 自動生成新的 product_id
        insert_query = products_table.insert().values(**values)
        await database.execute(insert_query)

    # 2. 回傳最新配置 (確認是否成功寫入)
    updated_product = await get_latest_product_config()
    
    # 為了保持前端相容性，手動加入 bids: []
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
        
    return {"status": "ok", "score": {"A": cfg.A, "B": cfg.B, "C": cfg.C}}