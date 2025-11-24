from flask import Flask, send_from_directory

app = Flask(__name__)

@app.route("/audio")
def audio():
    return send_from_directory(".", "frontend-audio.html")

@app.route("/video")
def video():
    return send_from_directory(".", "frontend-video.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, ssl_context="adhoc")