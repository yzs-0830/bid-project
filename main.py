from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# routers
from routers import bidding, admin, users  # users 之後會用到

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# include routers
app.include_router(bidding.router, prefix="/api")
app.include_router(admin.router,  prefix="/admin")
app.include_router(users.router,  prefix="/user")
