import secrets
import sqlite3
from pydantic import BaseModel
from fastapi import FastAPI, Depends, HTTPException, Header
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi import BackgroundTasks
import datetime

#later on make it so theres a collection per person (by api key) so everything can be diffrent per person

def log_request(route: str, api_key: str):
    with open("requests.log", "a") as f:
        f.write(f"{datetime.datetime.now()} - {route} - {api_key}\n")
# logging for /add

app = FastAPI()


def get_api_key(request: Request) -> str:
    return request.headers.get("x-api-key", "unknown")

limiter = Limiter(key_func=get_api_key)
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Try again later!"}
    )
#rate limiting setup

class RegisterBody(BaseModel):
    name: str

conni = sqlite3.connect("app.db")
cursors = conni.cursor()

cursors.execute("""
    CREATE TABLE IF NOT EXISTS api_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL UNIQUE,
        owner TEXT NOT NULL
    )
""")
conni.commit()
#api key database

def create_api_key(owner: str) -> str:
    key = secrets.token_hex(16)
    cursors.execute(
        "INSERT INTO api_keys (key, owner) VALUES (?, ?)",
        (key, owner)
    )
    conni.commit()
    return key

@app.post("/register")
async def register(body: RegisterBody):
    key = create_api_key(body.name)
    return {"api_key": key, "message": "Save this key! You won't be able to see it again."}

async def verify_api_key(x_api_key: str = Header()):
    cursors.execute("SELECT * FROM api_keys WHERE key = ?", (x_api_key,))
    result = cursors.fetchone()
    if result is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return result

@app.get("/secret-data", dependencies=[Depends(verify_api_key)])
async def get_secret_data():
    return {"message": "You have access!"}

# Everything above is for api keys

class Card(BaseModel):
    card_name: str
    card_set: str
    card_number: str
    condition: str
    est_value: int
#class setup for adding cards

conn = sqlite3.connect("collection.db")
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS collection (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_name TEXT NOT NULL,
        card_set TEXT NOT NULL,
        card_number INTEGER DEFAULT 0,
        condition TEXT NOT NULL,
        est_value INTEGER DEFAULT 0
    )
""")
conn.commit()

@app.get("/collection", dependencies=[Depends(verify_api_key)])
@limiter.limit("5/minute")
async def get_collection(request: Request):
    conn = sqlite3.connect("collection.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM collection")
    collection = cursor.fetchall()
    conn.close()
    return [{"id": b[0], "card_name": b[1], "card_set": b[2], "card_number": b[3], "condition": b[4], "est_value": b[5]} for b in collection]
#shows list of collection with rate limit of 5 requests per minute

@app.post("/add", dependencies=[Depends(verify_api_key)])
async def add_card(card: Card, background_tasks: BackgroundTasks):
    background_tasks.add_task(log_request, "/add", "some_key")
    conn = sqlite3.connect("collection.db")
    cursor = conn.cursor()

    cursor.execute(
    "INSERT INTO collection (card_name, card_set, card_number, condition, est_value) VALUES (?, ?, ?, ?, ?)",
    (card.card_name, card.card_set, card.card_number, card.condition, card.est_value)
)
    conn.commit()
    return f"Card {card.card_name} added"
#adds a new card using the Card Class (reuqires api key) (this gets logged)

@app.patch("/update/{card_id}", dependencies=[Depends(verify_api_key)])
async def update(card_id: int, upd_cond: str | None = None, upd_val: int | None = None):
    conn = sqlite3.connect("collection.db")
    cursor = conn.cursor()

    cursor.execute("SELECT card_name FROM collection WHERE id = ?", (card_id,))
    result = cursor.fetchone()
    card_name = result[0] if result else None

    if card_name is None:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Card with id {card_id} not found")

    elif upd_val is None and upd_cond is not None:
        cursor.execute("""
        UPDATE collection
        SET condition = ?
        WHERE id = ?
    """, (upd_cond, card_id))
        conn.commit()
        conn.close()
        return f"Card {card_name} condition updated to {upd_cond}"
    elif upd_val is not None and upd_cond is None:
        cursor.execute("""
        UPDATE collection
        SET est_value = ?
        WHERE id = ?
    """, (upd_val, card_id))
        conn.commit()
        conn.close()
        return f"Card {card_name} value updated to {upd_val}"
    elif upd_val is not None and upd_cond is not None:
        cursor.execute("""
        UPDATE collection
        SET condition = ?, est_value = ?
        WHERE id = ?
    """, (upd_cond, upd_val, card_id))
        conn.commit()
        conn.close()
        return f"Card {card_name} value updated to {upd_val} and condition updated to {upd_cond}"
# update condition and/or est value (requires api key)

@app.delete("/delete/{card_id}", dependencies=[Depends(verify_api_key)])
async def delete(card_id: int):
    conn = sqlite3.connect("collection.db")
    cursor = conn.cursor()

    cursor.execute("SELECT card_name FROM collection WHERE id = ?", (card_id,))
    result = cursor.fetchone()
    card_name = result[0] if result else None

    if card_name is None:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Card with id {card_id} not found")
    
    cursor.execute("DELETE FROM collection WHERE id = ?", (card_id,))
    conn.commit()
    conn.close()
    return f"Card {card_name} deleted from collection"
#delete card from collection based on id (requires api key)

@app.get("/total_value")
def total_value():
    conn = sqlite3.connect("collection.db")
    cursor = conn.cursor()

    cursor.execute("SELECT SUM(est_value) FROM collection")
    result = cursor.fetchone()
    total_val = result[0] if result else None

    if total_val is None:
        conn.close()
        raise HTTPException(status_code=404, detail="No cards in database with value to calculate")
    
    return {"total_value": total_val}
#calculate and return total value of collection

def main():
    import uvicorn
    uvicorn.run("resolution_week4_YOUR_USERNAME.main:app", host="127.0.0.1", port=8000)

if __name__ == "__main__":
    main()