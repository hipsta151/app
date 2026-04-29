from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import requests
from datetime import datetime

app = Flask(__name__)

# Your Google Apps Script Web App URL (you'll get this in Step 2)
SHEET_URL = "https://script.google.com/macros/s/AKfycbwCkW7X9SmEpvsfpDH4oFAARwAryLsiMEywQyy4_PeO7E-uu9hkqPMJgPzOxVSu-ib2/exec"

# Store session data per user (in-memory, simple)
sessions = {}

def save_to_sheet(data):
    requests.post(SHEET_URL, json=data)

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    incoming = request.form.get("Body", "").strip()
    sender   = request.form.get("From", "")
    resp     = MessagingResponse()
    msg      = resp.message()

    session = sessions.get(sender, {})
    text    = incoming.upper()

    # --- Step 1: Set Machine ---
    if text.startswith("MC "):
        mc = incoming[3:].strip().upper()
        sessions[sender] = {"mc": mc, "step": "menu"}
        msg.body(
            f"✅ Machine set: *{mc}*\n\n"
            "What do you want to log?\n"
            "1️⃣ DOWNTIME\n"
            "2️⃣ PERFORMANCE\n"
            "3️⃣ QUANTITY\n"
            "Reply with the number."
        )

    elif not session:
        msg.body("👋 Welcome!\nFirst, set your machine:\nSend: *MC B3-1F-CASSEROLE-IMM-A2-160MT*")

    elif session.get("step") == "menu":
        if text == "1":
            sessions[sender]["step"] = "downtime_reason"
            msg.body("⏱ *DOWNTIME*\nEnter reason for downtime:\n(e.g. Mould change, Power failure, Maintenance)")
        elif text == "2":
            sessions[sender]["step"] = "performance_ct"
            msg.body("⚙️ *PERFORMANCE*\nEnter actual cycle time (seconds):\n(Standard CT will be compared automatically)")
        elif text == "3":
            sessions[sender]["step"] = "qty_good"
            msg.body("📦 *QUANTITY*\nEnter good product count:")
        else:
            msg.body("Please reply 1, 2, or 3.")

    # --- Downtime flow ---
    elif session.get("step") == "downtime_reason":
        sessions[sender]["dt_reason"] = incoming
        sessions[sender]["step"] = "downtime_duration"
        msg.body("How long was the downtime?\nEnter in minutes (e.g. 45)")

    elif session.get("step") == "downtime_duration":
        save_to_sheet({
            "timestamp": datetime.now().isoformat(),
            "machine":   session["mc"],
            "type":      "DOWNTIME",
            "detail":    f"Reason: {session['dt_reason']} | Duration: {incoming} mins",
            "operator":  sender
        })
        sessions[sender] = {"mc": session["mc"], "step": "menu"}
        msg.body(f"✅ Downtime saved!\nReason: {session['dt_reason']}\nDuration: {incoming} mins\n\nLog more? Reply 1/2/3 or change machine: MC <id>")

    # --- Performance flow ---
    elif session.get("step") == "performance_ct":
        sessions[sender]["actual_ct"] = incoming
        sessions[sender]["step"] = "performance_std"
        msg.body("Enter standard (software) CT in seconds:")

    elif session.get("step") == "performance_std":
        actual = float(session["actual_ct"])
        std    = float(incoming)
        perf   = round((std / actual) * 100, 1) if actual > 0 else 0
        save_to_sheet({
            "timestamp": datetime.now().isoformat(),
            "machine":   session["mc"],
            "type":      "PERFORMANCE",
            "detail":    f"Actual CT: {actual}s | Std CT: {std}s | Performance: {perf}%",
            "operator":  sender
        })
        sessions[sender] = {"mc": session["mc"], "step": "menu"}
        msg.body(f"✅ Performance saved!\nActual CT: {actual}s\nStd CT: {std}s\n📊 Performance: *{perf}%*\n\nLog more? Reply 1/2/3")

    # --- Quantity flow ---
    elif session.get("step") == "qty_good":
        sessions[sender]["good"] = incoming
        sessions[sender]["step"] = "qty_reject"
        msg.body("Enter rejection count:")

    elif session.get("step") == "qty_reject":
        good   = int(session["good"])
        reject = int(incoming)
        total  = good + reject
        quality = round((good / total) * 100, 1) if total > 0 else 0
        save_to_sheet({
            "timestamp": datetime.now().isoformat(),
            "machine":   session["mc"],
            "type":      "QUANTITY",
            "detail":    f"Good: {good} | Reject: {reject} | Quality: {quality}%",
            "operator":  sender
        })
        sessions[sender] = {"mc": session["mc"], "step": "menu"}
        msg.body(f"✅ Quantity saved!\nGood: {good} | Reject: {reject}\n📊 Quality: *{quality}%*\n\nLog more? Reply 1/2/3")

    else:
        sessions[sender] = {}
        msg.body("Something went wrong. Send *MC <machine_id>* to start over.")

    return str(resp)

if __name__ == "__main__":
    app.run(debug=True)