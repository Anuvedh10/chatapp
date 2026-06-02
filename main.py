# main.py
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pymongo import MongoClient
from bson import ObjectId
import os
import datetime
import cloudinary
import cloudinary.uploader
import firebase_admin
from firebase_admin import credentials, messaging

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB
client = MongoClient(os.environ["MONGO_URI"])
db = client["chatapp"]
users_col = db["users"]
messages_col = db["messages"]
tokens_col = db["tokens"]

# Firebase Admin Init
cred = credentials.Certificate("/etc/secrets/serviceAccountKey.json")
firebase_admin.initialize_app(cred)

# Cloudinary Init
cloudinary.config(
    cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
    api_key=os.environ["CLOUDINARY_API_KEY"],
    api_secret=os.environ["CLOUDINARY_API_SECRET"],
)

class User(BaseModel):
    username: str
    password: str

class Message(BaseModel):
    sender: str
    receiver: str
    text: str

class TokenData(BaseModel):
    username: str
    token: str

# ── Auth ──────────────────────────────────────────────
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

# ── Users ─────────────────────────────────────────────
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

# ── FCM Token Register ────────────────────────────────
@app.post("/register-token")
def register_token(data: TokenData):
    tokens_col.update_one(
        {"username": data.username},
        {"$set": {"username": data.username, "token": data.token}},
        upsert=True
    )
    return {"status": "ok"}

# ── Push Notification Helper ──────────────────────────
def send_push(receiver: str, sender: str, text: str):
    try:
        doc = tokens_col.find_one({"username": receiver})
        if not doc or not doc.get("token"):
            return
        preview = text
        if text.startswith("↩ ") and "\n" in text:
            preview = text.split("\n", 1)[1]
        if text.startswith("[IMAGE]:"):
            preview = "📷 Photo"
        elif text.startswith("[VIDEO]:"):
            preview = "🎥 Video"

        message = messaging.Message(
            notification=messaging.Notification(
                title=sender,
                body=preview[:100],
            ),
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    channel_id="chatapp_channel",
                    sound="default",
                ),
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound="default"),
                ),
            ),
            token=doc["token"],
        )
        messaging.send(message)
    except Exception as e:
        print(f"Push failed: {e}")

# ── Messages ──────────────────────────────────────────
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
    send_push(msg.receiver, msg.sender, msg.text)
    return {"message": "sent", "id": str(result.inserted_id)}

# ── Media Upload (Cloudinary) ─────────────────────────
@app.post("/upload")
async def upload_file(
    sender: str = Form(...),
    receiver: str = Form(...),
    file: UploadFile = File(...)
):
    try:
        ext = file.filename.split(".")[-1].lower()
        allowed_image = ["jpg", "jpeg", "png", "gif", "webp"]
        allowed_video = ["mp4", "mov", "avi", "mkv"]
        allowed = allowed_image + allowed_video

        if ext not in allowed:
            raise HTTPException(status_code=400, detail="File type not allowed")

        is_video = ext in allowed_video
        resource_type = "video" if is_video else "image"

        # Upload to Cloudinary
        file_bytes = await file.read()
        result = cloudinary.uploader.upload(
            file_bytes,
            resource_type=resource_type,
            folder="chatapp",
            public_id=f"{sender}_{datetime.datetime.utcnow().timestamp()}",
        )

        file_url = result["secure_url"]
        msg_text = f"{'[VIDEO]' if is_video else '[IMAGE]'}:{file_url}"

        doc = {
            "sender": sender,
            "receiver": receiver,
            "text": msg_text,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "read": False,
            "deleted": False,
        }
        insert_result = messages_col.insert_one(doc)
        send_push(receiver, sender, msg_text)
        return {"message": "uploaded", "id": str(insert_result.inserted_id), "url": file_url}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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

# ── Typing ────────────────────────────────────────────
@app.get("/typing/{sender}/{receiver}")
def typing_status(sender: str, receiver: str):
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
