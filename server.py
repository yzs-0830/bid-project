from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import time

app = FastAPI()

# CORS：允許前端連線
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------
# 全域共享資料
# --------------------------
score = {
    "A": 3,
    "B": 5,
    "C": 3
}

product = {
    "name": "尚無商品",
    "base_price": 0,
    "total_quantity": 0,
    "bids": [],
    "start_time": 0,
    "period": 0
}

# --------------------------
# Models
# --------------------------
class ProductConfig(BaseModel):
    name: str
    base_price: float
    total_quantity: int
    duration_minutes: int

class ScoreConfig(BaseModel):
    A: int
    B: int
    C: int

class Bid(BaseModel):
    user_id: str
    bid_price: int

# --------------------------
# Score Function
# --------------------------
def Score(Price, Time, Weight):
    return score["A"]*Price + (score["B"]/(Time+1)) + score["C"]*Weight

import time # 確保已匯入

@app.post("/bid")
def set_a(value: Bid):
    current_timestamp = int(time.time() * 1000)
    time_elapsed = current_timestamp - product["start_time"]
    time_for_score = max(time_elapsed, 1) 

    bid_score = Score(value.bid_price, time_for_score, 1)
    product["bids"].append({
        "user_id": value.user_id, 
        "bid_price": value.bid_price, 
        "score": bid_score,
        "timestamp": current_timestamp
    })

    return {"status": "ok", "bid_price": value.bid_price, "score": bid_score}


@app.get("/get_bid_price")
def get_bid_price(user_id: str = Query(...)):
    """取得此 user_id 的最高出價及分數"""

    # 找出該使用者所有出價，並找出最高價的出價紀錄
    user_bids = [b for b in product["bids"] if b["user_id"] == user_id]

    if not user_bids:
        return {
            "user_id": user_id,
            "highest_bid": 0,
            "score": 0,
            "message": "此使用者尚未出價"
        }

    highest_bid_record = max(user_bids, key=lambda b: b["score"])
    highest_price = highest_bid_record["bid_price"]
    highest_score = highest_bid_record["score"] 

    return {
        "user_id": user_id,
        "highest_bid": highest_price,
        "score": highest_score, # ⭐️ 使用儲存的分數
        "product": product["name"]
    }

@app.get("/get_product")
def get_product():
    return product

@app.get("/bid_list")
def get_bid_list():
    sorted_bids = sorted(product["bids"], key=lambda x: x["score"], reverse=True)
    return sorted_bids[:product["total_quantity"]]

'''---------------------------------------------'''
'''--------------------ADMIN--------------------'''
'''---------------------------------------------'''
@app.post("/admin/set_product")
def admin_set_product(cfg: ProductConfig):
    current_time = int(time.time() * 1000)
    product["name"] = cfg.name
    product["base_price"] = cfg.base_price
    product["total_quantity"] = cfg.total_quantity
    product["bids"] = []  # 清空舊出價（上架新商品）
    product["start_time"] = current_time
    product["period"] = cfg.duration_minutes * 60 * 1000
    return {"status": "ok", "product": product}

# 設定 Score ABC
@app.post("/admin/set_score")
def admin_set_score(cfg: ScoreConfig):
    score["A"] = cfg.A
    score["B"] = cfg.B
    score["C"] = cfg.C
    return {"status": "ok", "score": score}