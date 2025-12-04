from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
import time
import sqlalchemy
from database import database, members_table, products_table, bids_table, winners_table

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
    # 避免除以 0，T 至少為 0 (秒/毫秒需統一，這裡假設 T 是秒或經過轉換的單位)
    # 若 T 是毫秒，分母 +1 影響很小，請確認業務邏輯。這裡沿用您的公式。
    return alpha * P + (beta / (T + 1)) + gamma * W

async def get_current_product():
    """獲取當前商品 (假設 ID=1)"""
    query = sqlalchemy.select(products_table).where(products_table.c.product_id == 1)
    return await database.fetch_one(query)

async def get_product_bids():
    """獲取當前商品的所有出價"""
    query = sqlalchemy.select(bids_table)
    return await database.fetch_all(query)

# --------------------------
# 核心邏輯：結算
# --------------------------

async def settle_product_logic(product_id: int, total_quantity: int):
    """
    結算邏輯：
    1. 計算得標者
    2. 開啟事務 (Transaction)
    3. 更新會員資料 & 寫入得標紀錄 (winners)
    4. 更新商品狀態
    """
    # ---------------------------------------------------------
    # 步驟 1: 計算得標者 (在記憶體中處理)
    # ---------------------------------------------------------
    
    # 優化建議：如果系統未來有多個商品，這裡應該要 filter product_id
    # query = sqlalchemy.select(bids_table).where(bids_table.c.product_id == product_id)
    all_bids = await database.fetch_all(sqlalchemy.select(bids_table))
    
    bids_data = [dict(b) for b in all_bids]
    sorted_bids = sorted(bids_data, key=lambda x: x["score"], reverse=True)

    winners = []
    seen_users = set()

    for bid in sorted_bids:
        user = bid["user_id"]
        if user not in seen_users:
            winners.append(bid)
            seen_users.add(user)
        if len(winners) >= total_quantity:
            break
            
    current_time = int(time.time() * 1000)

    # ---------------------------------------------------------
    # 步驟 2: 資料庫寫入 (全部包在同一個 Transaction)
    # ---------------------------------------------------------
    async with database.transaction():
        # A. 處理每一位贏家
        for win_bid in winners:
            u_id = win_bid["user_id"]
            
            # 1. 查出該會員目前資料
            # (注意：在高並發下，這裡建議使用 SELECT ... FOR UPDATE，但在 asyncpg/databases 寫法較複雜，
            # 若您的 settle_product_logic 保證同一時間只有一個程序在跑，這樣寫暫時沒問題)
            member = await database.fetch_one(
                sqlalchemy.select(members_table).where(members_table.c.user_id == u_id)
            )
            
            if member:
                new_wins = member["wins"] + 1
                
                # 2. 更新會員權重 (Update Member)
                await database.execute(
                    sqlalchemy.update(members_table)
                    .where(members_table.c.user_id == u_id)
                    .values(wins=new_wins, weight=new_wins)
                )

            # 3. 寫入得標紀錄 (Insert Winner)
            # 這是您缺少的關鍵步驟，現在補回來了
            await database.execute(
                winners_table.insert().values(
                    product_id=product_id,
                    user_id=u_id,
                    win_price=win_bid["bid_price"],
                    win_score=win_bid["score"],
                    settled_time=current_time
                )
            )

        # B. 更新商品為已結算 (Update Product)
        await database.execute(
            sqlalchemy.update(products_table)
            .where(products_table.c.product_id == product_id)
            .values(settled=True)
        )
    
    print(f"Product {product_id} settled. Winners count: {len(winners)}")

# --------------------------
# API 路由
# --------------------------

@router.post("/bid")
async def bid(value: BidModel):
    # 1. 獲取商品資訊
    product = await get_current_product()
    if not product:
        return {"status": "fail", "message": "目前無活動商品"}

    # 2. 檢查是否已結算
    if product["settled"]:
        return {"status": "fail", "message": "商品已結算，無法出價"}

    # 3. 獲取會員真實權重
    member = await database.fetch_one(
        sqlalchemy.select(members_table).where(members_table.c.user_id == value.user_id)
    )
    if not member:
        return {"status": "fail", "message": "請先註冊或登入"}
    
    W = member["weight"]

    # 4. 計算分數
    current_timestamp = int(time.time() * 1000)
    start_time = product["start_time"] or 0 # 防止 None 報錯
    
    # 計算時間差 (毫秒)
    time_elapsed = current_timestamp - start_time
    
    # 防止 T 為 0 或負數導致公式異常
    time_for_score = max(time_elapsed, 1) 

    # 讀取參數 (如果 DB 欄位名不同請自行調整)
    alpha = product["alpha"]
    beta = product["beta"]
    gamma = product["gamma"]

    bid_score = calc_score(value.bid_price, time_for_score, W, alpha, beta, gamma)

    # 5. 寫入出價到資料庫 (INSERT)
    query = bids_table.insert().values(
        user_id=value.user_id,
        bid_price=value.bid_price,
        score=bid_score,
        timestamp=current_timestamp
    )
    await database.execute(query)

    return {
        "status": "ok", 
        "bid_price": value.bid_price, 
        "score": bid_score,
        "timestamp": current_timestamp
    }


@router.get("/get_bid_price")
async def get_bid_price(user_id: str = Query(...)):
    # 查詢該用戶所有出價
    query = sqlalchemy.select(bids_table).where(bids_table.c.user_id == user_id)
    user_bids = await database.fetch_all(query)

    if not user_bids:
        return {
            "user_id": user_id,
            "highest_bid": 0,
            "score": 0,
            "message": "尚未出價"
        }

    # 找出最高分紀錄 (轉為 dict 處理)
    bids_list = [dict(b) for b in user_bids]
    highest_record = max(bids_list, key=lambda b: b["score"])

    # 獲取商品名稱
    product = await get_current_product()
    prod_name = product["name"] if product else "未知商品"

    return {
        "user_id": user_id,
        "highest_bid": highest_record["bid_price"],
        "score": highest_record["score"],
        "product": prod_name
    }


@router.get("/bid_list")
async def bid_list():
    """回傳前 K 名暫定得標者"""
    product = await get_current_product()
    if not product:
        return []

    limit_k = product["total_quantity"]

    # 查詢所有出價並排序
    # 優化: 這裡用 Python 處理 Distinct User 邏輯 (SQL 寫法較複雜)
    query = sqlalchemy.select(bids_table) # 實際環境建議加 Order By score desc
    all_bids = await database.fetch_all(query)
    
    # 轉 dict 並排序
    sorted_bids = sorted([dict(b) for b in all_bids], key=lambda x: x["score"], reverse=True)

    result = []
    seen = set()
    for b in sorted_bids:
        if b["user_id"] not in seen:
            result.append(b)
            seen.add(b["user_id"])
        if len(result) >= limit_k:
            break
            
    return result


@router.get("/get_product")
async def get_product():
    # 1. 獲取當前商品
    product = await get_current_product()
    
    # 若無商品，回傳安全的預設空物件
    if not product:
        return {
            "name": "尚無商品", 
            "base_price": 0, 
            "total_quantity": 0, 
            "bids": [], 
            "start_time": 0, 
            "period": 0, 
            "settled": True, 
            "winner": []  # 🌟 確保有這個欄位
        }

    product_dict = dict(product) # 轉為可變字典
    
    # 2. 檢查是否過期需要結算
    now = int(time.time() * 1000)
    end_time = (product_dict["start_time"] or 0) + (product_dict["period"] or 0)

    # 若未結算且時間已到 -> 觸發結算
    if not product_dict["settled"] and now >= end_time:
        # 呼叫結算邏輯 (寫入 winners 表、更新 settled 狀態)
        await settle_product_logic(product_dict["product_id"], product_dict["total_quantity"])
        
        # 結算後重新讀取最新商品狀態
        product = await get_current_product()
        product_dict = dict(product)

    # 3. 🌟 新增：讀取得標者名單 (從 winners 表)
    # 這是為了解決關聯式資料庫無法在 products 表直接存陣列的問題
    winners_list = []
    if product_dict["settled"]:
        query = sqlalchemy.select(winners_table).where(winners_table.c.product_id == product_dict["product_id"])
        winner_records = await database.fetch_all(query)
        # 取出 user_id 轉成 list，例如 ['user1', 'user2']
        winners_list = [w["user_id"] for w in winner_records]
    
    # 將名單掛回字典，讓前端可以讀取 product.winner
    product_dict["winner"] = winners_list

    # 4. 讀取並掛載出價列表 (兼容前端 product.bids)
    # (注意：若資料量大，這裡建議未來優化為只抓前幾名或分頁)
    bids_query = sqlalchemy.select(bids_table)
    bids_records = await database.fetch_all(bids_query)
    product_dict["bids"] = [dict(b) for b in bids_records]

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