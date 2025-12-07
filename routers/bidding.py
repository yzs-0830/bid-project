from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
import time
import sqlalchemy
import json
import math
import random
from database import database, members_table, products_table, winners_table, redis_client

router = APIRouter()

# 定義請求模型
class BidModel(BaseModel):
    user_id: str
    bid_price: int

# --------------------------
# 🔥 核心優化 1: 燒機程式 (為了觸發 Auto Scaling)
# --------------------------
def burn_cpu():
    """
    純消耗 CPU 運算，強迫負載升高。
    因為 Redis 太快了，不加這個 ASG 不會擴展。
    """
    x = 0
    for i in range(10000): 
        x += i * i
    return x

# --------------------------
# 輔助函式
# --------------------------

def calc_score(P, T, W, alpha, beta, gamma):
    """計算分數公式"""
    return alpha * P + (beta / (T + 1)) + gamma * W

async def get_current_product():
    """
    🔥 核心優化 2: 商品資訊快取 (Lazy Loading)
    邏輯：先查 Redis -> 沒有才查 SQL -> 寫入 Redis (1小時)
    """
    cache_key = "system:current_product"

    # 1. 嘗試從 Redis 讀取
    cached_data = await redis_client.get(cache_key)
    if cached_data:
        return json.loads(cached_data)

    # 2. Redis 沒資料，查 SQL (只有第一次或過期會進來)
    query = (
        sqlalchemy.select(products_table)
        .order_by(products_table.c.product_id.desc())
        .limit(1)
    )
    row = await database.fetch_one(query)

    if row:
        product_data = dict(row)
        
        # 轉成 JSON 友善格式
        cache_payload = {
            "product_id": product_data["product_id"],
            "name": product_data["name"],
            # 確保有預設值
            "start_time": product_data["start_time"] or int(time.time()*1000), 
            "period": product_data["period"] or 0,
            "total_quantity": product_data["total_quantity"] or 0,
            "settled": product_data["settled"],
            "base_price": product_data["base_price"],
            "alpha": product_data["alpha"] or 3.0,
            "beta": product_data["beta"] or 5.0,
            "gamma": product_data["gamma"] or 3.0
        }

        # 寫入 Redis，設定 1 小時過期 (防止 NaN 閃爍問題)
        await redis_client.set(cache_key, json.dumps(cache_payload), ex=3600)
        
        return product_data
    
    return None

async def get_user_weight(user_id: str):
    """
    🔥 核心優化 3: 用戶權重快取
    邏輯：先查 Redis -> 沒有才查 SQL -> 寫入 Redis
    """
    user_key = f"user:{user_id}"
    
    # 1. 查 Redis Hash
    weight = await redis_client.hget(user_key, "weight")
    if weight is not None:
        return int(weight)
    
    # 2. 查 SQL (Fallback)
    query = sqlalchemy.select(members_table).where(members_table.c.user_id == user_id)
    member = await database.fetch_one(query)
    
    if member:
        w = member["weight"]
        # 補寫入 Redis，避免下次還要查 SQL
        await redis_client.hset(user_key, "weight", w)
        # 設定過期 (例如 1 小時)
        await redis_client.expire(user_key, 3600)
        return w
    
    return 1 # 預設值，避免報錯

# --------------------------
# 核心邏輯：結算
# --------------------------

async def settle_product_logic(product_id: int, total_quantity: int):
    print(f"🚀 開始結算商品 {product_id}...")

    async with database.transaction():
        # A. 悲觀鎖
        query = sqlalchemy.select(products_table).where(products_table.c.product_id == product_id).with_for_update()
        product_record = await database.fetch_one(query)

        if not product_record or product_record["settled"]:
            print("商品已結算，跳過。")
            return

        # B. Redis 取贏家
        ranking_key = f"{{bid:{product_id}}}:ranking"
        details_hash_key = f"{{bid:{product_id}}}:details"
        top_users_with_scores = await redis_client.zrevrange(ranking_key, 0, total_quantity - 1, withscores=True)
        current_time = int(time.time() * 1000)

        # C. 寫入 SQL & 更新 Redis 用戶權重
        for user_id, score in top_users_with_scores:
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
                
                # 🔥🔥🔥 修正點 1: 這裡必須同步更新 Redis！
                # 不然前端/API 從 Redis 拿到的權重永遠是舊的 (0)
                await redis_client.hset(f"user:{user_id}", "weight", new_wins)
                print(f"✅ 用戶 {user_id} 權重已更新為 {new_wins}")

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

        # D. 更新商品狀態 SQL
        await database.execute(
            sqlalchemy.update(products_table)
            .where(products_table.c.product_id == product_id)
            .values(settled=True)
        )
        
        # E. Redis 清理
        await redis_client.expire(ranking_key, 3600)
        await redis_client.expire(details_hash_key, 3600)

        # F. 主動更新 Redis 商品快取 (settled=True)
        cache_key = "system:current_product"
        current_redis = await redis_client.get(cache_key)
        if current_redis:
            try:
                p_json = json.loads(current_redis)
                if p_json.get("product_id") == product_id:
                    p_json["settled"] = True
                    # 注意：我們不把贏家塞進 Redis，因為您說要從 SQL 拿
                    await redis_client.set(cache_key, json.dumps(p_json), ex=3600)
            except: pass
        
    print(f"✅ 商品 {product_id} 結算完成。")

# --------------------------
# API 路由
# --------------------------

@router.post("/bid")
async def bid(value: BidModel):
    # 🔥 1. 燒機 (AWS Demo 必要！)
    burn_cpu()

    # 🔥 2. 獲取商品 (改為讀 Redis，不查 SQL)
    product = await get_current_product()
    if not product: return {"status": "fail", "message": "無商品"}
    if product["settled"]: return {"status": "fail", "message": "已結算"}

    # 🔥 3. 獲取權重 (改為讀 Redis，不查 SQL)
    W = await get_user_weight(value.user_id)

    # 4. 計算分數
    current_timestamp = int(time.time() * 1000)
    start_time = product["start_time"] or 0
    time_elapsed = max(current_timestamp - start_time, 1)
    
    bid_score = calc_score(
        value.bid_price, 
        time_elapsed, 
        W, 
        product["alpha"], 
        product["beta"], 
        product["gamma"]
    )

    # 5. 寫入 Redis (Pipeline 原子操作)
    ranking_key = f"{{bid:{product['product_id']}}}:ranking"
    details_hash_key = f"{{bid:{product['product_id']}}}:details"
    
    async with redis_client.pipeline(transaction=True) as pipe:
        # A. 寫入排行榜
        await pipe.zadd(ranking_key, {value.user_id: bid_score})
        # B. 寫入詳細資訊
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
    product = await get_current_product()
    if not product: return []
    
    ranking_key = f"{{bid:{product['product_id']}}}:ranking"
    details_hash_key = f"{{bid:{product['product_id']}}}:details"
    
    # 只取前 K 名
    top_users = await redis_client.zrevrange(ranking_key, 0, product["total_quantity"] - 1, withscores=True)
    
    result = []
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

@router.get("/get_product")
async def get_product_api():
    # 1. 獲取商品 (優先讀 Redis)
    product = await get_current_product()
    
    if not product:
        return {"name": "尚無商品", "base_price": 0, "total_quantity": 0, "bids": [], "start_time": 0, "settled": True, "winner": []}

    # 將 Redis 的 dict 轉為可變物件
    product_dict = dict(product)
    
    # 2. 自動結算檢查 (Lazy Settlement)
    now = int(time.time() * 1000)
    end_time = (product_dict["start_time"] or 0) + (product_dict["period"] or 0)

    if not product_dict["settled"] and now >= end_time:
        # 觸發結算
        await settle_product_logic(product_dict["product_id"], product_dict["total_quantity"])
        # 重新讀取 (這時 Redis 裡的 settled 應該已經變成 True 了)
        product = await get_current_product() 
        product_dict = dict(product)

    # -----------------------------------------------------------
    # 🔥🔥🔥 修正點 2: 贏家名單必須從 SQL 拿！
    # -----------------------------------------------------------
    # Redis 裡面的 product_dict 沒有 winner 欄位 (或不準)。
    # 如果已結算，我們必須去 SQL 的 winners_table 查出名單，
    # 然後塞進回傳給前端的 JSON 裡。
    
    winners_list = []
    if product_dict.get("settled"):
        # 查詢 SQL
        query = sqlalchemy.select(winners_table).where(winners_table.c.product_id == product_dict["product_id"])
        winner_records = await database.fetch_all(query)
        # 提取 user_id 列表
        winners_list = [w["user_id"] for w in winner_records]
    
    # 將 SQL 查到的贏家合併進去
    product_dict["winner"] = winners_list

    # 3. 補上 bids (從 Redis 讀取即時出價)
    product_dict["bids"] = await bid_list()
    
    return product_dict

@router.get("/get_bid_price")
async def get_bid_price(user_id: str = Query(...)):
    latest_prod = await get_current_product()
    pid = latest_prod['product_id'] if latest_prod else 1
    
    ranking_key = f"{{bid:{pid}}}:ranking"
    details_hash_key = f"{{bid:{pid}}}:details"
    
    score = await redis_client.zscore(ranking_key, user_id)
    if score is None:
        return {"user_id": user_id, "highest_bid": 0, "score": 0, "message": "尚未出價"}
    
    detail_json = await redis_client.hget(details_hash_key, user_id)
    price = 0
    if detail_json:
        price = json.loads(detail_json).get("price", 0)
        
    return {"user_id": user_id, "highest_bid": price, "score": score}

@router.post("/reset_all_data")
async def reset_all_data():
    """本地測試神器：一鍵重置所有資料"""
    try:
        await redis_client.flushall()
        async with database.transaction():
            await database.execute("TRUNCATE TABLE winners, members, products RESTART IDENTITY CASCADE")
        return {"status": "ok", "message": "系統已完全重置"}
    except Exception as e:
        return {"status": "error", "message": str(e)}