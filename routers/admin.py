# routers/admin.py

from fastapi import APIRouter
from pydantic import BaseModel
import time

from data import product, score

router = APIRouter()


class ProductConfig(BaseModel):
    name: str
    base_price: float
    total_quantity: int
    duration_minutes: int


class ScoreConfig(BaseModel):
    A: int
    B: int
    C: int


@router.post("/set_product")
def set_product(cfg: ProductConfig):
    current_time = int(time.time() * 1000)

    product["name"] = cfg.name
    product["base_price"] = cfg.base_price
    product["total_quantity"] = cfg.total_quantity
    product["bids"] = []  # 清空舊出價
    product["start_time"] = current_time
    product["period"] = cfg.duration_minutes * 60 * 1000
    product["settled"] = False
    product["winner"] = []

    return {"status": "ok", "product": product}


@router.post("/set_score")
def set_score(cfg: ScoreConfig):
    score["A"] = cfg.A
    score["B"] = cfg.B
    score["C"] = cfg.C
    return {"status": "ok", "score": score}
