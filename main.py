from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pymongo import MongoClient
from bson import ObjectId
import os
import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

client = MongoClient(os.environ["MONGO_URI"])
db = client["chatapp"]
users_col = db["users"]
messages_col = db["messages"]

class User(BaseModel):
    username: str
    password: str

class Message(BaseModel):
    sender: str
    receiver: str
    text: str

@app.post("/register")
def register(user: User):
    if users_col.find_one({"username": user.username}):
        raise HTTPException(status_code=400, detail="Username already exists")
    users_col.insert_one({"username": user.username, "password": user.password})
    return {"message": "Registration Successful"}

@app.post("/login")
def login(user: User):
    u = users_col.find_one({"username": user.username, "password": user.password})
    if not u:
        raise HTTPException(status_code=401, detail="Invalid Username or Password")
    return {"message": "Login Successful"}

@app.get("/users")
def get_users():
    users = users_col.find({}, {"_id": 0, "username": 1})
    return [u["username"] for u in users]

@app.get("/conversations/{username}")
def get_conversations(username: str):
    msgs = messages_col.find(
        {"$or": [{"sender": username}, {"receiver": username}]},
        {"_id": 0}
    )
    contacts = set()
    for m in msgs:
        if m["sender"] == username:
            contacts.add(m["receiver"])
        else:
            contacts.add(m["sender"])
    return list(contacts)

@app.post("/send")
def send_message(msg: Message):
    doc = {
        "sender": msg.sender,
        "receiver": msg.receiver,
        "text": msg.text,
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "read": False,
        "deleted": False,
    }
    result = messages_col.insert_one(doc)
    return {"message": "sent", "id": str(result.inserted_id)}

@app.get("/chat/{user1}/{user2}")
def get_chat(user1: str, user2: str):
    msgs = messages_col.find(
        {
            "$or": [
                {"sender": user1, "receiver": user2},
                {"sender": user2, "receiver": user1}
            ],
            "deleted": {"$ne": True}
        }
    )
    result = []
    for m in msgs:
        result.append({
            "id": str(m["_id"]),
            "sender": m["sender"],
            "receiver": m["receiver"],
            "text": m["text"],
            "timestamp": m.get("timestamp", ""),
            "read": m.get("read", False),
        })
    return result

@app.post("/read/{sender}/{receiver}")
def mark_read(sender: str, receiver: str):
    messages_col.update_many(
        {"sender": sender, "receiver": receiver, "read": False},
        {"$set": {"read": True}}
    )
    return {"message": "marked read"}

@app.delete("/message/{message_id}")
def delete_message(message_id: str):
    try:
        messages_col.update_one(
            {"_id": ObjectId(message_id)},
            {"$set": {"deleted": True}}
        )
        return {"message": "deleted"}
    except:
        raise HTTPException(status_code=400, detail="Invalid message id")

@app.get("/typing/{sender}/{receiver}")
def typing_status(sender: str, receiver: str):
    # Simple polling-based typing — client sets, others read
    key = f"{sender}_to_{receiver}"
    doc = db["typing"].find_one({"key": key})
    if not doc:
        return {"typing": False}
    elapsed = (datetime.datetime.utcnow() - doc["updated"]).total_seconds()
    return {"typing": elapsed < 3}

@app.post("/typing/{sender}/{receiver}")
def set_typing(sender: str, receiver: str):
    key = f"{sender}_to_{receiver}"
    db["typing"].update_one(
        {"key": key},
        {"$set": {"key": key, "updated": datetime.datetime.utcnow()}},
        upsert=True
    )
    return {"ok": True}
