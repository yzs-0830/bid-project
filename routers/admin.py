from fastapi import APIRouter
from pydantic import BaseModel
import time
import sqlalchemy
from database import database, products_table, bids_table

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

async def get_current_product_config():
    """從資料庫獲取當前商品的詳細配置 (假設 ID=1)"""
    query = sqlalchemy.select(products_table).where(products_table.c.product_id == 1)
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
        # winner 欄位在 SQL 中比較複雜，這裡先不處理，結算時再更新
    }

    async with database.transaction():
        # 2. 清空舊的出價紀錄 (模擬 product["bids"] = [])
        # ⚠️ 注意：因為我們是單商品系統，上架新商品時應清除舊出價
        await database.execute(bids_table.delete())

        # 3. 更新或新增商品 (Upsert product_id=1)
        # 檢查是否存在
        query = sqlalchemy.select(products_table).where(products_table.c.product_id == 1)
        exists = await database.fetch_one(query)

        if exists:
            # Update
            update_query = (
                sqlalchemy.update(products_table)
                .where(products_table.c.product_id == 1)
                .values(**values)
            )
            await database.execute(update_query)
        else:
            # Insert (強制 product_id=1)
            insert_query = products_table.insert().values(product_id=1, **values)
            await database.execute(insert_query)

    # 4. 回傳最新配置
    updated_product = await get_current_product_config()
    
    # 為了保持前端相容性，手動加入 bids: []
    updated_product["bids"] = []
    
    return {"status": "ok", "product": updated_product}


@router.post("/set_score")
async def set_score(cfg: ScoreConfig):
    # 更新 product_id=1 的 alpha, beta, gamma
    values = {
        "alpha": cfg.A,
        "beta": cfg.B,
        "gamma": cfg.C
    }

    # 檢查商品是否存在
    query = sqlalchemy.select(products_table).where(products_table.c.product_id == 1)
    exists = await database.fetch_one(query)

    if exists:
        update_query = (
            sqlalchemy.update(products_table)
            .where(products_table.c.product_id == 1)
            .values(**values)
        )
        await database.execute(update_query)
        
        # 回傳更新後的權重
        return {"status": "ok", "score": {"A": cfg.A, "B": cfg.B, "C": cfg.C}}
    else:
        # 如果商品還沒建立，可能無法設定分數 (視邏輯而定)
        # 這裡選擇先建立一個預設商品或報錯，簡單起見回傳失敗
        return {"status": "fail", "message": "請先上架商品後再設定分數"}