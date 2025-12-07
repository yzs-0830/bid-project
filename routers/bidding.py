from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
import time
import sqlalchemy
import json  # 🌟 新增：用於 Redis 資料處理
from database import database, members_table, products_table, winners_table, redis_client

# 注意：高併發架構下，我們不再使用 SQL 的 bids_table
# from database import bids_table 

router = APIRouter()

# 定義請求模型
class BidModel(BaseModel):
    user_id: str
    bid_price: int

# --------------------------
# 輔助函式
# --------------------------

def calc_score(P, T, W, alpha, beta, gamma):
    """計算分數公式"""
    return alpha * P + (beta / (T + 1)) + gamma * W

async def get_current_product():
    """獲取當前商品 (邏輯：取 ID 最大的最新商品)"""
    query = (
        sqlalchemy.select(products_table)
        .order_by(products_table.c.product_id.desc())
        .limit(1)
    )
    return await database.fetch_one(query)

# --------------------------
# 核心邏輯：結算 (Redis -> SQL)
# --------------------------

async def settle_product_logic(product_id: int, total_quantity: int):
    """
    結算邏輯：
    1. 悲觀鎖定商品 (SQL)
    2. 從 Redis 取出贏家
    3. 寫入 SQL (Winners, Members)
    4. 更新商品狀態
    5. 設定 Redis 過期
    """
    print(f"🚀 開始結算商品 {product_id}...")

    # 1. 開啟 SQL Transaction
    async with database.transaction():
        # A. 悲觀鎖：鎖住商品防止重複結算
        query = sqlalchemy.select(products_table).where(products_table.c.product_id == product_id).with_for_update()
        product_record = await database.fetch_one(query)

        if not product_record or product_record["settled"]:
            print("商品已結算，跳過。")
            return

        # B. 🌟 從 Redis Sorted Set 取出前 K 名贏家
        ranking_key = f"{{bid:{product_id}}}:ranking"
        details_hash_key = f"{{bid:{product_id}}}:details"
        
        # ZREVRANGE: 分數由高到低，取前 total_quantity 名 (含分數)
        top_users_with_scores = await redis_client.zrevrange(ranking_key, 0, total_quantity - 1, withscores=True)

        current_time = int(time.time() * 1000)

        # C. 處理每一位贏家
        for user_id, score in top_users_with_scores:
            # 從 Redis Hash 獲取詳細出價資訊
            detail_json = await redis_client.hget(details_hash_key, user_id)
            
            price = 0
            if detail_json:
                detail = json.loads(detail_json)
                price = detail.get("price", 0)

            # 1. 更新 SQL 會員資料 (Wins + 1)
            member = await database.fetch_one(sqlalchemy.select(members_table).where(members_table.c.user_id == user_id))
            if member:
                new_wins = member["wins"] + 1
                await database.execute(
                    sqlalchemy.update(members_table)
                    .where(members_table.c.user_id == user_id)
                    .values(wins=new_wins, weight=new_wins)
                )

            # 2. 寫入 SQL 得標紀錄 (Winners Table)
            await database.execute(
                winners_table.insert().values(
                    product_id=product_id,
                    user_id=user_id,
                    win_price=price,
                    win_score=score,
                    settled_time=current_time
                )
            )

        # D. 更新商品為已結算 (Products Table)
        await database.execute(
            sqlalchemy.update(products_table)
            .where(products_table.c.product_id == product_id)
            .values(settled=True)
        )
        
        # E. 設定 Redis 資料自動過期 (1小時後清除，釋放記憶體)
        await redis_client.expire(ranking_key, 3600)
        await redis_client.expire(details_hash_key, 3600)
        
    print(f"✅ 商品 {product_id} 結算完成。贏家: {len(top_users_with_scores)} 人")


# --------------------------
# API 路由
# --------------------------

@router.post("/bid")
async def bid(value: BidModel):
    # 1. 獲取商品資訊
    product = await get_current_product()
    if not product: return {"status": "fail", "message": "無商品"}
    if product["settled"]: return {"status": "fail", "message": "已結算"}

    # 2. 獲取會員權重
    member = await database.fetch_one(sqlalchemy.select(members_table).where(members_table.c.user_id == value.user_id))
    if not member: return {"status": "fail", "message": "請先註冊或登入"}
    W = member["weight"]

    # 3. 計算分數
    current_timestamp = int(time.time() * 1000)
    start_time = product["start_time"] or 0
    time_elapsed = max(current_timestamp - start_time, 1)
    
    # 參數對應：P, T, W, alpha, beta, gamma
    bid_score = calc_score(
        value.bid_price, 
        time_elapsed, 
        W, 
        product["alpha"], 
        product["beta"], 
        product["gamma"]
    )

    # 4. 🌟 寫入 Redis (取代 SQL INSERT)
    ranking_key = f"{{bid:{product['product_id']}}}:ranking"
    details_hash_key = f"{{bid:{product['product_id']}}}:details"
    
    # Pipeline 原子性寫入
    async with redis_client.pipeline(transaction=True) as pipe:
        # A. 排行榜 (ZSET)
        await pipe.zadd(ranking_key, {value.user_id: bid_score})
        
        # B. 詳細資訊 (HASH)
        detail_data = json.dumps({
            "price": value.bid_price, 
            "time": current_timestamp, 
            "score": bid_score
        })
        await pipe.hset(details_hash_key, value.user_id, detail_data)
        
        await pipe.execute()

    return {
        "status": "ok", 
        "bid_price": value.bid_price, 
        "score": bid_score, 
        "timestamp": current_timestamp
    }


@router.get("/bid_list")
async def bid_list():
    """從 Redis 讀取即時排行榜"""
    product = await get_current_product()
    if not product: return []
    
    # 1. 從 Redis ZSET 撈取前 K 名
    ranking_key = f"{{bid:{product['product_id']}}}:ranking"
    details_hash_key = f"{{bid:{product['product_id']}}}:details"
    
    top_users = await redis_client.zrevrange(ranking_key, 0, product["total_quantity"] - 1, withscores=True)
    
    result = []
    # 2. 組合詳細資料
    for user_id, score in top_users:
        detail_json = await redis_client.hget(details_hash_key, user_id)
        
        price = 0
        timestamp = 0
        if detail_json:
            d = json.loads(detail_json)
            price = d.get("price")
            timestamp = d.get("time")
            
        result.append({
            "user_id": user_id,
            "bid_price": price,
            "score": score,
            "timestamp": timestamp
        })
        
    return result


@router.get("/get_bid_price")
async def get_bid_price(user_id: str = Query(...)):
    """從 Redis 取得用戶狀態"""
    # 取得最新商品 ID
    latest_prod = await get_current_product()
    pid = latest_prod['product_id'] if latest_prod else 1
    
    ranking_key = f"{{bid:{pid}}}:ranking"
    details_hash_key = f"{{bid:{pid}}}:details"
    
    # 1. 查分數
    score = await redis_client.zscore(ranking_key, user_id)
    if score is None:
        return {"user_id": user_id, "highest_bid": 0, "score": 0, "message": "尚未出價"}
    
    # 2. 查詳細價格
    detail_json = await redis_client.hget(details_hash_key, user_id)
    price = 0
    if detail_json:
        price = json.loads(detail_json).get("price", 0)
        
    return {
        "user_id": user_id,
        "highest_bid": price,
        "score": score,
        "product": latest_prod["name"] if latest_prod else "Unknown"
    }


@router.get("/get_product")
async def get_product():
    # 1. 獲取當前商品
    product = await get_current_product()
    
    if not product:
        return {
            "name": "尚無商品", 
            "base_price": 0, 
            "total_quantity": 0, 
            "bids": [], 
            "start_time": 0, 
            "period": 0, 
            "settled": True, 
            "winner": [] 
        }

    product_dict = dict(product)
    
    # 2. 自動結算檢查
    now = int(time.time() * 1000)
    end_time = (product_dict["start_time"] or 0) + (product_dict["period"] or 0)

    if not product_dict["settled"] and now >= end_time:
        # 呼叫 Redis 結算邏輯
        await settle_product_logic(product_dict["product_id"], product_dict["total_quantity"])
        
        # 重新讀取
        product = await get_current_product()
        product_dict = dict(product)

    # 3. 讀取 Winners (從 SQL)
    winners_list = []
    if product_dict["settled"]:
        query = sqlalchemy.select(winners_table).where(winners_table.c.product_id == product_dict["product_id"])
        winner_records = await database.fetch_all(query)
        winners_list = [w["user_id"] for w in winner_records]
    
    product_dict["winner"] = winners_list

    # 4. 讀取 Bids (從 Redis，與 /bid_list 邏輯共用)
    product_dict["bids"] = await bid_list()

    return product_dict


@router.get("/get_score")
async def get_score():
    """回傳分數權重設定"""
    product = await get_current_product()
    if product:
        return {
            "A": product["alpha"], 
            "B": product["beta"], 
            "C": product["gamma"]
        }
    return {"A": 0, "B": 0, "C": 0}


@router.get("/user_info")
async def user_info(username: str):
    query = sqlalchemy.select(members_table).where(members_table.c.user_id == username)
    member = await database.fetch_one(query)
    
    if not member:
        return {"status": "fail", "message": "用戶不存在"}
        
    return {
        "status": "ok",
        "username": member["user_id"],
        "weight": member["weight"]
    }

@router.get("/redis_check")
async def check_redis_connection():
    try:
        response = await redis_client.ping()
        if response:
            return {"status": "ok", "message": "Redis is connected."}
        else:
            return {"status": "fail", "message": "Redis ping failed."}
    except Exception as e:
        return {"status": "error", "message": f"Connection Error: {e}"}