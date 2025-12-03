from fastapi import APIRouter, Query
from pydantic import BaseModel
import time

from data import product, score, members

router = APIRouter()

class Bid(BaseModel):
    user_id: str
    bid_price: int

# Score function
def calc_score(P, T, W):
    return score["A"] * P + (score["B"] / (T + 1)) + score["C"] * W

def settle_product():
    if not product["bids"]:
        product["settled"] = True
        product["winner"] = []
        return

    # 依照 score 排序，從大到小
    sorted_bids = sorted(product["bids"], key=lambda x: x["score"], reverse=True)

    winners = []
    seen_users = set()

    # 遍歷排序後的出價，取前 total_quantity 個不同使用者
    for bid in sorted_bids:
        user = bid["user_id"]
        if user not in seen_users:
            winners.append(bid)
            seen_users.add(user)
        if len(winners) >= product["total_quantity"]:
            break

    # 更新會員 wins 與 weight
    for bid in winners:
        user = bid["user_id"]
        if user in members:
            members[user]["wins"] = members[user].get("wins", 0) + 1
            members[user]["weight"] = members[user]["wins"]

    product["settled"] = True
    product["winner"] = [bid["user_id"] for bid in winners]



@router.post("/bid")
def bid(value: Bid):
    current_timestamp = int(time.time() * 1000)
    time_elapsed = current_timestamp - product["start_time"]
    time_for_score = max(time_elapsed, 1)

    # 🌟 修正：從 members 獲取當前使用者的 weight
    user = value.user_id
    if user not in members:
        return {"status": "fail", "message": "請先註冊或登入"}

    W = members[user]["weight"]  # ⭐ 從會員系統帶入真實 weight
    
    # 檢查是否已結算
    if product.get("settled"):
        return {"status": "fail", "message": "商品已結算，無法出價"}

    bid_score = calc_score(value.bid_price, time_for_score, W)

    product["bids"].append({
        "user_id": value.user_id,
        "bid_price": value.bid_price,
        "score": bid_score,
        "timestamp": current_timestamp
    })

    return {"status": "ok", "bid_price": value.bid_price, "score": bid_score}


@router.get("/get_bid_price")
def get_bid_price(user_id: str = Query(...)):
    user_bids = [b for b in product["bids"] if b["user_id"] == user_id]

    if not user_bids:
        return {
            "user_id": user_id,
            "highest_bid": 0,
            "score": 0,
            "message": "此使用者尚未出價"
        }

    highest_record = max(user_bids, key=lambda b: b["score"])

    return {
        "user_id": user_id,
        "highest_bid": highest_record["bid_price"],
        "score": highest_record["score"],
        "product": product["name"]
    }


@router.get("/bid_list")
def bid_list():
    sorted_bids = sorted(product["bids"], key=lambda x: x["score"], reverse=True)    
    return sorted_bids[:product["total_quantity"]]


@router.get("/get_product")
def get_product():
    now = int(time.time()*1000)
    if not product.get("settled") and now >= product["start_time"] + product["period"]:
        settle_product()
    return product

@router.get("/get_score")
def get_product():
    return score

@router.get("/user_info")
def user_info(username: str):
    if username not in members:
        return {"status": "fail", "message": "用戶不存在"}
    return {
        "status": "ok",
        "username": username,
        "weight": members[username]["weight"]
    }