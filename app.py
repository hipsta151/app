from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import requests
from datetime import datetime
import os

app = Flask(__name__)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
# Paste your Google Apps Script Web App URL here after deploying
SHEET_URL = os.environ.get("SHEET_URL", "https://script.google.com/macros/s/AKfycbxyKvcAYZ-i0u73VqRjQ87ySNWKM8RlAIaO96ZmLwhel2ghRRSc_z0LRPygwOz_brF7/exec")

# Standard cycle times per machine (seconds) — update as needed
STANDARD_CT = {
    "DEFAULT": 30,
    "B3-1F-CASSEROLE-IMM-A2-160MT": 28,
    "B3-1F-CASSEROLE-IMM-A1-120MT": 25,
}

# ─── SESSION STORE (in-memory) ────────────────────────────────────────────────
sessions = {}

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def save_to_sheet(data):
    try:
        requests.post(SHEET_URL, json=data, timeout=5)
    except Exception as e:
        print(f"Sheet save error: {e}")

def get_std_ct(machine_id):
    return STANDARD_CT.get(machine_id.upper(), STANDARD_CT["DEFAULT"])

def menu_text(mc):
    return (
        f"📋 Machine: *{mc}*\n\n"
        "What do you want to log?\n"
        "1️⃣  DOWNTIME\n"
        "2️⃣  PERFORMANCE\n"
        "3️⃣  QUANTITY\n"
        "4️⃣  ALL IN ONE (full shift log)\n\n"
        "Or type *MC <id>* to change machine\n"
        "Or type *STATUS* to see today's summary"
    )

# ─── MAIN WEBHOOK ─────────────────────────────────────────────────────────────
@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    incoming = request.form.get("Body", "").strip()
    sender   = request.form.get("From", "")
    resp     = MessagingResponse()
    msg      = resp.message()

    session = sessions.get(sender, {})
    text    = incoming.strip().upper()

    # ── Set Machine ──────────────────────────────────────────────────────────
    if text.startswith("MC "):
        mc = incoming[3:].strip().upper()
        sessions[sender] = {"mc": mc, "step": "menu"}
        msg.body(
            f"✅ Machine set!\n*{mc}*\n\n"
            + menu_text(mc)
        )
        return str(resp)

    # ── No session yet ───────────────────────────────────────────────────────
    if not session:
        msg.body(
            "👋 *Welcome to OEE Logger!*\n\n"
            "First, set your machine ID:\n"
            "Send: *MC B3-1F-CASSEROLE-IMM-A2-160MT*\n\n"
            "_(Replace with your actual machine ID)_"
        )
        return str(resp)

    mc   = session.get("mc", "UNKNOWN")
    step = session.get("step", "menu")

    # ── STATUS command ───────────────────────────────────────────────────────
    if text == "STATUS":
        msg.body(
            f"📊 *Current Session Info*\n"
            f"Machine: {mc}\n"
            f"Standard CT: {get_std_ct(mc)}s\n"
            f"Send 1/2/3/4 to log data."
        )
        return str(resp)

    # ── MENU ─────────────────────────────────────────────────────────────────
    if step == "menu":
        if text == "1":
            sessions[sender]["step"] = "dt_reason"
            msg.body(
                "⏱ *DOWNTIME ENTRY*\n\n"
                "Enter downtime reason:\n"
                "_(e.g. Mould change, Power failure, Maintenance, Material shortage)_"
            )
        elif text == "2":
            std = get_std_ct(mc)
            sessions[sender]["step"] = "perf_actual_ct"
            msg.body(
                f"⚙️ *PERFORMANCE ENTRY*\n\n"
                f"Standard CT for *{mc}*: *{std}s*\n\n"
                "Enter actual running cycle time (seconds):"
            )
        elif text == "3":
            sessions[sender]["step"] = "qty_good"
            msg.body("📦 *QUANTITY ENTRY*\n\nEnter *good product* count:")
        elif text == "4":
            sessions[sender]["step"] = "all_dt_reason"
            msg.body(
                "📝 *FULL SHIFT LOG*\n\n"
                "Step 1/6: Enter downtime reason\n"
                "_(type SKIP if no downtime)_"
            )
        else:
            msg.body(menu_text(mc))
        return str(resp)

    # ══════════════════════════════════════════════════════════════════════════
    # DOWNTIME FLOW  (1)
    # ══════════════════════════════════════════════════════════════════════════
    if step == "dt_reason":
        sessions[sender]["dt_reason"] = incoming
        sessions[sender]["step"] = "dt_duration"
        msg.body("⏱ Enter downtime duration in *minutes*:\n_(e.g. 45)_")

    elif step == "dt_duration":
        try:
            duration = float(incoming)
        except ValueError:
            msg.body("❌ Please enter a valid number (minutes).\nE.g. 45")
            return str(resp)

        reason = session.get("dt_reason", "-")
        save_to_sheet({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "machine":   mc,
            "shift":     session.get("shift", ""),
            "type":      "DOWNTIME",
            "dt_reason": reason,
            "dt_duration_min": duration,
            "actual_ct": "",
            "std_ct":    "",
            "performance_pct": "",
            "good_qty":  "",
            "reject_qty": "",
            "quality_pct": "",
            "operator":  sender
        })
        sessions[sender] = {"mc": mc, "step": "menu"}
        msg.body(
            f"✅ *Downtime Saved!*\n"
            f"Machine: {mc}\n"
            f"Reason: {reason}\n"
            f"Duration: {duration} mins\n\n"
            + menu_text(mc)
        )

    # ══════════════════════════════════════════════════════════════════════════
    # PERFORMANCE FLOW  (2)
    # ══════════════════════════════════════════════════════════════════════════
    elif step == "perf_actual_ct":
        try:
            actual_ct = float(incoming)
        except ValueError:
            msg.body("❌ Please enter a valid number (seconds).\nE.g. 32")
            return str(resp)

        std_ct = get_std_ct(mc)
        perf   = round((std_ct / actual_ct) * 100, 1) if actual_ct > 0 else 0

        save_to_sheet({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "machine":   mc,
            "shift":     session.get("shift", ""),
            "type":      "PERFORMANCE",
            "dt_reason": "",
            "dt_duration_min": "",
            "actual_ct": actual_ct,
            "std_ct":    std_ct,
            "performance_pct": perf,
            "good_qty":  "",
            "reject_qty": "",
            "quality_pct": "",
            "operator":  sender
        })
        sessions[sender] = {"mc": mc, "step": "menu"}

        status = "🟢" if perf >= 80 else "🟡" if perf >= 60 else "🔴"
        msg.body(
            f"✅ *Performance Saved!*\n"
            f"Machine: {mc}\n"
            f"Actual CT: {actual_ct}s | Std CT: {std_ct}s\n"
            f"{status} Performance: *{perf}%*\n\n"
            + menu_text(mc)
        )

    # ══════════════════════════════════════════════════════════════════════════
    # QUANTITY FLOW  (3)
    # ══════════════════════════════════════════════════════════════════════════
    elif step == "qty_good":
        try:
            sessions[sender]["good_qty"] = int(incoming)
            sessions[sender]["step"] = "qty_reject"
            msg.body("📦 Enter *rejection* count:")
        except ValueError:
            msg.body("❌ Please enter a valid whole number.\nE.g. 350")

    elif step == "qty_reject":
        try:
            reject  = int(incoming)
            good    = session.get("good_qty", 0)
            total   = good + reject
            quality = round((good / total) * 100, 1) if total > 0 else 0
        except ValueError:
            msg.body("❌ Please enter a valid whole number.\nE.g. 12")
            return str(resp)

        save_to_sheet({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "machine":   mc,
            "shift":     session.get("shift", ""),
            "type":      "QUANTITY",
            "dt_reason": "",
            "dt_duration_min": "",
            "actual_ct": "",
            "std_ct":    "",
            "performance_pct": "",
            "good_qty":  good,
            "reject_qty": reject,
            "quality_pct": quality,
            "operator":  sender
        })
        sessions[sender] = {"mc": mc, "step": "menu"}

        status = "🟢" if quality >= 98 else "🟡" if quality >= 95 else "🔴"
        msg.body(
            f"✅ *Quantity Saved!*\n"
            f"Machine: {mc}\n"
            f"Good: {good} | Reject: {reject} | Total: {total}\n"
            f"{status} Quality: *{quality}%*\n\n"
            + menu_text(mc)
        )

    # ══════════════════════════════════════════════════════════════════════════
    # ALL-IN-ONE FLOW  (4)  — Downtime → Performance → Quantity
    # ══════════════════════════════════════════════════════════════════════════
    elif step == "all_dt_reason":
        if text == "SKIP":
            sessions[sender]["all_dt_reason"] = ""
            sessions[sender]["all_dt_dur"]    = 0
        else:
            sessions[sender]["all_dt_reason"] = incoming
        sessions[sender]["step"] = "all_dt_dur"
        if text == "SKIP":
            sessions[sender]["step"] = "all_actual_ct"
            std = get_std_ct(mc)
            msg.body(f"Step 2/6: Enter actual cycle time (seconds)\nStd CT: {std}s")
        else:
            msg.body("Step 2/6: Enter downtime duration (minutes):")

    elif step == "all_dt_dur":
        try:
            sessions[sender]["all_dt_dur"] = float(incoming)
        except ValueError:
            msg.body("❌ Enter a valid number (minutes).")
            return str(resp)
        sessions[sender]["step"] = "all_actual_ct"
        std = get_std_ct(mc)
        msg.body(f"Step 3/6: Enter actual cycle time (seconds)\nStd CT for {mc}: {std}s")

    elif step == "all_actual_ct":
        try:
            sessions[sender]["all_actual_ct"] = float(incoming)
        except ValueError:
            msg.body("❌ Enter a valid number (seconds).")
            return str(resp)
        sessions[sender]["step"] = "all_good_qty"
        msg.body("Step 4/6: Enter *good product* count:")

    elif step == "all_good_qty":
        try:
            sessions[sender]["all_good"] = int(incoming)
        except ValueError:
            msg.body("❌ Enter a valid whole number.")
            return str(resp)
        sessions[sender]["step"] = "all_reject_qty"
        msg.body("Step 5/6: Enter *rejection* count:")

    elif step == "all_reject_qty":
        try:
            sessions[sender]["all_reject"] = int(incoming)
        except ValueError:
            msg.body("❌ Enter a valid whole number.")
            return str(resp)
        sessions[sender]["step"] = "all_shift"
        msg.body("Step 6/6: Enter shift number (1, 2, or 3):")

    elif step == "all_shift":
        # Calculate everything
        dt_reason  = session.get("all_dt_reason", "-")
        dt_dur     = session.get("all_dt_dur", 0)
        actual_ct  = session.get("all_actual_ct", 0)
        std_ct     = get_std_ct(mc)
        good       = session.get("all_good", 0)
        reject     = session.get("all_reject", 0)
        total      = good + reject
        shift      = incoming.strip()

        perf    = round((std_ct / actual_ct) * 100, 1) if actual_ct > 0 else 0
        quality = round((good / total) * 100, 1) if total > 0 else 0

        # Availability: assume 8hr shift = 480 min
        avail = round(((480 - dt_dur) / 480) * 100, 1)
        oee   = round((avail / 100) * (perf / 100) * (quality / 100) * 100, 1)

        save_to_sheet({
            "timestamp":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "machine":          mc,
            "shift":            shift,
            "type":             "FULL SHIFT",
            "dt_reason":        dt_reason,
            "dt_duration_min":  dt_dur,
            "actual_ct":        actual_ct,
            "std_ct":           std_ct,
            "performance_pct":  perf,
            "good_qty":         good,
            "reject_qty":       reject,
            "quality_pct":      quality,
            "operator":         sender
        })
        sessions[sender] = {"mc": mc, "step": "menu"}

        oee_status = "🟢" if oee >= 80 else "🟡" if oee >= 60 else "🔴"
        msg.body(
            f"✅ *Full Shift Log Saved!*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏭 Machine: {mc}\n"
            f"🔄 Shift: {shift}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⏱ Downtime: {dt_dur} mins ({dt_reason})\n"
            f"📊 Availability: *{avail}%*\n"
            f"⚙️ Performance: *{perf}%* ({actual_ct}s vs {std_ct}s)\n"
            f"📦 Quality: *{quality}%* ({good} good / {reject} reject)\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{oee_status} OEE: *{oee}%*\n\n"
            + menu_text(mc)
        )

    else:
        sessions[sender] = {}
        msg.body("⚠️ Session reset.\nSend *MC <machine_id>* to start.")

    return str(resp)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
