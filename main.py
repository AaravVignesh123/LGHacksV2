from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
from twilio.rest import Client
from flask_cors import CORS


app = Flask(__name__)
CORS(app)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///proto.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ---- DB Models ----
class Device(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String, unique=True)
    location_name = db.Column(db.String)

class NGO(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    phone = db.Column(db.String)
    email = db.Column(db.String)
    lat = db.Column(db.Float)
    lon = db.Column(db.Float)
    services = db.Column(db.String)

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String)
    event_type = db.Column(db.String)
    raw = db.Column(db.String)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    matched_ngos = db.Column(db.String)
    status = db.Column(db.String, default="new")

with app.app_context():
    db.create_all()

# ---- NGO Matching Logic ----
def match_ngos_for_event(event_json):
    """Match NGOs based on services needed and proximity"""
    event_type = event_json.get('event_type', '')
    
    # Get all active NGOs
    ngos = NGO.query.all()
    
    if not ngos:
        print("WARNING: No NGOs registered in system!")
        return []
    
    # For prototype: return all NGOs for any alert
    # In production: filter by service type, location, capacity
    matched = ngos[:10]  # Limit to 3 NGOs
    
    print(f"Matched {len(matched)} NGOs for event type: {event_type}")
    return matched

# ---- Notification System ----
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
TWILIO_FROM = os.getenv("TWILIO_FROM")

def notify_ngos(ngos, event):
    """Send notifications to matched NGOs"""
    msgs = []
    
    for ngo in ngos:
        # Create alert message
        event_type = event.get('event_type', 'unknown')
        device_id = event.get('device_id', 'unknown')
        
        if event_type == "possible_encampment":
            text = f"🚨 ALERT: Person needs assistance at {device_id}. They have been present for 3+ minutes. Please respond."
        else:
            text = f"⚠️ NOTIFICATION: Motion detected at {device_id}. Monitoring situation."
        
        print(f"→ Notifying {ngo.name} ({ngo.phone}): {text}")
        msgs.append({"ngo": ngo.name, "phone": ngo.phone, "message": text})
        
        # Send SMS if Twilio is configured
        if TWILIO_SID and ngo.phone:
            try:
                client = Client(TWILIO_SID, TWILIO_TOKEN)
                client.messages.create(
                    body=text,
                    from_=TWILIO_FROM,
                    to=ngo.phone
                )
                print(f"  ✓ SMS sent successfully")
            except Exception as e:
                print(f"  ✗ Twilio error: {e}")
    
    return msgs

# ---- API Endpoints ----
@app.route("/api/event", methods=["POST"])
def receive_event():
    """Receive sensor event and notify NGOs"""
    data = request.get_json() or {}
    
    device_id = data.get("device_id", "unknown")
    event_type = data.get("event") or data.get("event_type") or "unknown"
    
    # Fix timestamp: use server time if not provided
    timestamp = datetime.utcnow()
    
    print(f"\n📥 Received event: {event_type} from {device_id}")
    
    # Save event to database
    ev = Event(
        device_id=device_id,
        event_type=event_type,
        raw=str(data),
        created_at=timestamp
    )
    db.session.add(ev)
    db.session.commit()
    
    # IMPORTANT: Only notify NGOs for critical alerts (not every motion detection)
    should_notify = event_type == "possible_encampment"
    
    if should_notify:
        print("🔔 Critical alert detected - matching NGOs...")
        
        # Match NGOs
        ngos = match_ngos_for_event(data)
        
        if ngos:
            # Send notifications
            notified = notify_ngos(ngos, data)
            
            # Update event with matched NGOs
            ev.matched_ngos = ",".join([str(n.id) for n in ngos])
            ev.status = "notified"
            db.session.commit()
            
            print(f"✓ Event #{ev.id} - Notified {len(ngos)} NGOs")
            
            return jsonify({
                "status": "ok",
                "event_id": ev.id,
                "notified": notified,
                "message": f"Alert sent to {len(ngos)} NGOs"
            })
        else:
            print("⚠️ No NGOs available to notify!")
            return jsonify({
                "status": "warning",
                "event_id": ev.id,
                "message": "Event saved but no NGOs registered"
            })
    else:
        # Just log the event, don't notify
        print(f"✓ Event #{ev.id} logged (no notification needed)")
        return jsonify({
            "status": "ok",
            "event_id": ev.id,
            "message": "Event logged"
        })

# ---- Admin Endpoints ----
@app.route("/admin/ngos", methods=["GET", "POST"])
def ngos():
    if request.method == "POST":
        j = request.get_json()
        n = NGO(
            name=j['name'],
            phone=j.get('phone'),
            email=j.get('email'),
            services=j.get('services', '')
        )
        db.session.add(n)
        db.session.commit()
        print(f"✓ Added NGO: {n.name} (ID: {n.id})")
        return jsonify({"id": n.id, "name": n.name})
    else:
        ngo_list = NGO.query.all()
        return jsonify([{
            "id": n.id,
            "name": n.name,
            "phone": n.phone,
            "email": n.email
        } for n in ngo_list])

@app.route("/admin/events")
def list_events():
    evs = Event.query.order_by(Event.created_at.desc()).limit(50).all()
    return jsonify([{
        "id": e.id,
        "device_id": e.device_id,
        "event_type": e.event_type,
        "created_at": e.created_at.isoformat(),
        "status": e.status,
        "matched_ngos": e.matched_ngos
    } for e in evs])


@app.route("/")
def index():
    """Serve the simple dashboard UI"""
    try:
        return render_template('index.html')
    except Exception:
        # Fall back to a minimal message if templates aren't available
        return (
            "<h1>Homeless Assistance Backend</h1>"
            "<p>API available under /api and /admin endpoints.</p>"
        )

@app.route("/admin/clear", methods=["POST"])
def clear_events():
    """Clear all events (useful for testing/resetting)"""
    try:
        num_deleted = Event.query.delete()
        db.session.commit()
        print(f"🗑️ Cleared {num_deleted} events from database")
        return jsonify({
            "status": "ok",
            "deleted": num_deleted,
            "message": f"Cleared {num_deleted} events"
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/admin/stats")
def stats():
    """Get system statistics"""
    total_events = Event.query.count()
    total_ngos = NGO.query.count()
    active_alerts = Event.query.filter_by(status="notified").count()
    
    return jsonify({
        "total_events": total_events,
        "total_ngos": total_ngos,
        "active_alerts": active_alerts
    })

if __name__ == "__main__":
    print("🚀 Starting Homeless Assistance Backend")
    print("📍 Server: http://127.0.0.1:5000")
    print("=" * 50)
    app.run(debug=True, host="0.0.0.0")


@app.route("/")
def index():
    return "index.html"
