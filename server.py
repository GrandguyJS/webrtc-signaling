# server.py
import os
from livekit import api
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv

load_dotenv("secret.env")

app = Flask(__name__)

@app.route('/getToken')
def getToken():
    pwd = request.args.get("pwd")
    if pwd != os.getenv("PASSWORD"):
        return jsonify({"error": "unauthorized"}), 401
    
    token = api.AccessToken(os.getenv('LIVEKIT_API_KEY'), os.getenv('LIVEKIT_API_SECRET')) \
        .with_identity("identity") \
        .with_name("my name") \
        .with_grants(api.VideoGrants(
            room_join=True,
            room="room1",
        ))
    print(token.to_jwt())
    return jsonify({"token": token.to_jwt()})

@app.route("/video")
def video():
    return send_from_directory("public", "frontend-video.html")

@app.route("/audio")
def audio():
    return send_from_directory("public", "frontend-audio.html")


if __name__ == '__main__':  
   app.run(host="0.0.0.0", port=8000)