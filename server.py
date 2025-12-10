# server.py
import os
from livekit import api
from flask import Flask, request, jsonify, send_from_directory
from flask import send_file
from werkzeug.utils import secure_filename
import time

from dotenv import load_dotenv
load_dotenv("secret.env")

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)

@app.route('/token')
def getToken():
    pwd = request.args.get("pwd")
    identity = request.args.get("identity")
    if pwd != os.getenv("PASSWORD"):
        return jsonify({"error": "unauthorized"}), 401
    
    token = api.AccessToken(os.getenv('LIVEKIT_API_KEY'), os.getenv('LIVEKIT_API_SECRET')) \
        .with_identity(identity) \
        .with_grants(api.VideoGrants(
            room_join=True,
            room="room1",
        ))
    return jsonify({"token": token.to_jwt()})

@app.route("/video")
def video():
    return send_from_directory("public", "frontend-video.html")

@app.route("/audio")
def audio():
    return send_from_directory("public", "frontend-audio.html")

@app.route("/upload-image", methods=["POST"])
def upload_image():
    f = request.files.get("file")
    if not f:
        return {"error": "no file"}, 400

    name = f"{int(time.time()*1000)}.jpg"
    path = os.path.join(UPLOAD_DIR, secure_filename(name))
    f.save(path)
    return {"ok": True, "name": name}

@app.route("/latest-image")
def latest_image():
    files = sorted(
        [os.path.join(UPLOAD_DIR, f) for f in os.listdir(UPLOAD_DIR)],
        key=os.path.getmtime,
        reverse=True,
    )
    if not files:
        return {"error": "no image"}, 404
    return send_file(files[0], mimetype="image/jpeg")

if __name__ == '__main__':  
   app.run(host="0.0.0.0", port=8000)