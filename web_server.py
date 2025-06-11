from flask import Flask, jsonify, render_template
import threading
import time
import yaml
import os
from datetime import datetime, timedelta

# Initialize Flask app
app = Flask(__name__, 
    template_folder=os.path.join(os.path.dirname(__file__), 'templates'))

# Get port from environment variable or use default
PORT = int(os.environ.get('PORT', 5002))

# These will be initialized by init_monitor
_check_device = None
_is_reachable = None
_send_alert = None

# Alert cooldown configuration (in minutes)
ALERT_COOLDOWN = 30  # Will only send repeat alerts every 30 minutes

def log(message):
    """Logging function"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] {message}"
    print(log_entry)
    
    # Ensure log directory exists
    log_dir = os.path.join(os.path.dirname(__file__), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    with open(os.path.join(log_dir, 'network_monitor.log'), 'a') as f:
        f.write(log_entry + '\n')

# Shared data structure to store device status
data = {
    "device_status": {}
}

# Track last alert time for each device
last_alert_times = {}

def can_send_alert(device_name):
    """Check if enough time has passed since the last alert for this device"""
    if device_name not in last_alert_times:
        return True
    
    time_since_last_alert = datetime.now() - last_alert_times[device_name]
    return time_since_last_alert > timedelta(minutes=ALERT_COOLDOWN)

def update_last_alert_time(device_name):
    """Update the last alert time for a device"""
    last_alert_times[device_name] = datetime.now()

def init_monitor(check_device, is_reachable, send_alert):
    """Initialize the monitor with required functions."""
    global _check_device, _is_reachable, _send_alert
    _check_device = check_device
    _is_reachable = is_reachable
    _send_alert = send_alert

def update_data():
    """Background thread to update device status data."""
    device_alert_state = {}  # Track previous alert state of devices
    
    while True:
        try:
            # Load devices from yaml config
            with open('/app/config/devices.yaml') as f:
                devices = yaml.safe_load(f)['devices']
            
            current_alerts = []
            for device in devices:
                try:
                    # Check device status
                    alerts = _check_device(device)
                    status = "Alert" if alerts else "OK"
                    is_reachable = _is_reachable(device["ip"])
                    
                    # Update device status in data structure
                    data["device_status"][device["name"]] = {
                        "status": status,
                        "messages": alerts,
                        "ip": device["ip"],
                        "reachable": is_reachable
                    }
                    
                    # Check if device state changed or if it's still in alert state
                    prev_state = device_alert_state.get(device["name"], {"reachable": True, "alerts": []})
                    state_changed = is_reachable != prev_state["reachable"] or alerts != prev_state["alerts"]
                    
                    if not is_reachable and (state_changed or can_send_alert(device["name"])):
                        alert_msg = f"Device {device['name']} ({device['ip']}) is unreachable"
                        current_alerts.append(alert_msg)
                        log(f"Adding alert: {alert_msg}")
                        if state_changed:
                            log(f"State change for {device['name']}: Previously {'reachable' if prev_state['reachable'] else 'unreachable'}")
                        update_last_alert_time(device["name"])
                            
                    # Update stored state
                    device_alert_state[device["name"]] = {
                        "reachable": is_reachable,
                        "alerts": alerts
                    }
                    
                except Exception as e:
                    log(f"Error processing device {device.get('name', 'unknown')}: {str(e)}")
                    continue
            
            # Send email if there are any alerts
            if current_alerts and _send_alert:
                alert_text = "Network Monitor Alerts:\n\n" + "\n".join(f"- {msg}" for msg in current_alerts)
                if len(current_alerts) > 1:
                    alert_text += f"\n\nNote: Next alert for these devices will be sent after {ALERT_COOLDOWN} minutes if they remain unreachable."
                else:
                    alert_text += f"\n\nNote: Next alert for this device will be sent after {ALERT_COOLDOWN} minutes if it remains unreachable."
                _send_alert(alert_text)
            
            time.sleep(5)  # Update every 5 seconds
            
        except Exception as e:
            log(f"Error in update thread: {str(e)}")
            time.sleep(10)  # Wait longer on error before retry

@app.route('/api/data')
def api_data():
    """API endpoint to return device status data as JSON."""
    return jsonify(data)

@app.route('/')
def index():
    """Serve the main webpage."""
    return render_template('index.html')

def start_web_server():
    """Start the web server and background monitoring thread."""
    # Start the background thread
    threading.Thread(target=update_data, daemon=True).start()
    
    # Run the Flask web server
    app.run(host='0.0.0.0', port=PORT)
