from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pymongo import MongoClient
import os

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

@app.post("/send")
def send_message(msg: Message):
    messages_col.insert_one({"sender": msg.sender, "receiver": msg.receiver, "text": msg.text})
    return {"message": "sent"}

@app.get("/chat/{user1}/{user2}")
def get_chat(user1: str, user2: str):
    msgs = messages_col.find(
        {"$or": [
            {"sender": user1, "receiver": user2},
            {"sender": user2, "receiver": user1}
        ]},
        {"_id": 0}
    )
    return list(msgs)
