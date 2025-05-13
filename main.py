import os
import logging
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from functools import wraps
import openai
from datetime import datetime, timedelta
from google.oauth2 import service_account
from google.cloud import firestore
from dotenv import load_dotenv

# --- Load Environment Variables ---
load_dotenv()

# --- Flask App Setup ---
app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.getenv("FLASK_SECRET_KEY", "your-very-secret-key")
# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chat-service")

# --- OpenAI API Key ---
openai.api_key = os.getenv("OPENAI_API_KEY")

# --- Session Security & Expiry ---
app.permanent_session_lifetime = timedelta(minutes=30)
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True

# --- Firestore Init ---
try:
    creds = service_account.Credentials.from_service_account_file(
        os.getenv("FIREBASE_CREDENTIALS")
    )
    db = firestore.Client(project=os.getenv("FIREBASE_PROJECT"), credentials=creds)
    logger.info("Firestore client initialized successfully")
except Exception as e:
    logger.error(f"Error initializing Firestore: {e}")


# --- Combine System Instructions ---
system_instruction = "\n".join([
    os.getenv("MATRIX_OS_CORE_MEMORY", ""),
    os.getenv("SYSTEM_PROMPT", ""),
    os.getenv("MATRIX_OSE_PROTOCOL", ""),
    os.getenv("ADDITIONAL_RULES", "")
])

# --- Chatbot Modes ---
bot_tabs = ["Rainmaker", "Insight-Magus", "Voice Sculptor", "ROI Architect"]
tab_prompts = {
    "Rainmaker": "🔹 You are in Rainmaker Mode (BizDev). Focus on clarity and strategic framing.",
    "Insight-Magus": "🔹 You are in Insight-Magus Mode (Strategy). Analyze logic and emotional patterns.",
    "Voice Sculptor": "🔹 You are in Voice Sculptor Mode (Copy). Refine brand tone and resonance.",
    "ROI Architect": "🔹 You are in ROI Architect Mode (Conversion). Prioritize proof layering and CTA."
}

# --- Decorators ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# --- Login Route ---
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        try:
            # Use the entered username to fetch the document
            user_ref = db.collection("users").document(username)
            user_doc = user_ref.get()
            print(f"Fetched user doc: {user_doc}")

            # Check if the document exists
            if user_doc.exists:
                user_data = user_doc.to_dict()
                print(f"User data: {user_data}")

                # Validate password
                if user_data.get("password") == password:
                    print(f"Password matched for {username}")
                    session["username"] = username
                    session.permanent = True
                    flash("Login successful!", "success")
                    return redirect(url_for("chat"))
                else:
                    flash("Invalid credentials", "danger")
            else:
                # Create a new user if not found
                print(f"User not found, creating new: {username}")
                user_ref.set({
                    "username": username,
                    "password": password,
                    "created_at": datetime.utcnow().isoformat()
                })
                session["username"] = username
                session.permanent = True
                flash("User created and logged in!", "success")
                return redirect(url_for("chat"))

        except Exception as e:
            logger.error(f"Login error: {e}")
            flash("Error during login", "danger")
    return render_template("login.html")


# --- Logout Route ---
@app.route("/logout")
def logout():
    try:
        username = session["username"]
        # Only clear the session cookie, not the chat history
        session.clear()
        flash("Logged out successfully!", "info")
        logger.info(f"User {username} logged out successfully")
        return redirect(url_for("login"))
    except Exception as e:
        logger.error(f"Error during logout: {e}")
        flash("Error during logout", "danger")
        return redirect(url_for("chat"))


@app.route("/resume_session/<active_tab>", methods=["GET"])
@login_required
def resume_session(active_tab):
    try:
        username = session["username"]
        doc = db.collection(f"users/{username}/bots/{active_tab}/active_session").document("last").get()
        if doc.exists:
            chat_id = doc.to_dict().get("chat_id")
            return jsonify({"chat_id": chat_id})
        return jsonify({"chat_id": None})
    except Exception as e:
        logger.error(f"Error resuming session: {e}")
        return jsonify({"chat_id": None})


# --- Chat Page ---
@app.route("/chat")
@login_required
def chat():
    username = session["username"]
    return render_template("chat.html", username=username, tabs=bot_tabs)
    
def generate_chat_id(bot_name):
    """Generate a unique chat ID based on the bot name and timestamp."""
    now = datetime.utcnow()
    return f"{bot_name}_{now.strftime('%Y%m%d_%H%M%S')}"


# --- Chat API Route ---
@app.route("/chat", methods=["POST"])
@login_required
def chat_api():
    try:
        data = request.get_json()
        user_input = data.get("message", "")
        active_tab = data.get("tab", "Rainmaker")
        chat_id = data.get("chat_id", None)
        username = session["username"]

        # Generate a new chat ID if not provided
        if not chat_id:
            chat_id = f"{active_tab}_{datetime.utcnow().isoformat()}"

        # Firestore path per bot session
        user_path = f"users/{username}/bots/{active_tab}/sessions/{chat_id}/messages"

        # Prepare messages for OpenAI
        messages = [{"role": "system", "content": system_instruction}]
        messages.append({"role": "system", "content": tab_prompts.get(active_tab, "")})

        # Retrieve chat history from Firestore (specific to the active bot and session)
        messages_ref = db.collection(user_path).order_by("timestamp").limit(20).stream()
        for msg in messages_ref:
            msg_data = msg.to_dict()
            messages.append({"role": msg_data["role"], "content": msg_data["content"]})

        # Add user message to Firestore
        db.collection(user_path).add({
            "role": "user",
            "content": user_input,
            "timestamp": datetime.utcnow().isoformat()
        })

        # OpenAI response (based on the specific bot's context)
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=1000,
            temperature=0.8
        )
        reply = response.choices[0].message.content.strip()

        # Save bot response to Firestore
        db.collection(user_path).add({
            "role": "assistant",
            "content": reply,
            "timestamp": datetime.utcnow().isoformat()
        })

        # Save the active chat session to Firestore
        db.collection(f"users/{username}/bots/{active_tab}/active_session").document("last").set({
            "chat_id": chat_id,
            "timestamp": datetime.utcnow().isoformat()
        })

        return jsonify({"reply": reply, "chat_id": chat_id})

    except Exception as e:
        logger.error(f"Chat error: {e}")
        return jsonify({"reply": "⚠️ Error processing your request."}), 500



@app.route("/delete_chat/<active_tab>/<chat_id>", methods=["GET"])
@login_required
def delete_chat(active_tab, chat_id):
    try:
        username = session["username"]
        # Firestore path
        user_path = f"users/{username}/bots/{active_tab}/sessions/{chat_id}"
        docs = db.collection(user_path).stream()
        for doc in docs:
            db.collection(user_path).document(doc.id).delete()
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Error deleting chat: {e}")
        return jsonify({"status": "error"}), 500



# --- Run Flask App ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9800)