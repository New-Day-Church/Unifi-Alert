from flask import Flask, jsonify, render_template, request
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

# Alert timing configuration (in minutes)
INITIAL_DELAY = 5  # Wait 5 minutes before sending first alert
ALERT_COOLDOWN = 360  # Wait 6 hours (360 minutes) between subsequent alerts

# Monitoring configuration (in seconds)
PING_INTERVAL = int(os.environ.get('PING_INTERVAL', 30))  # Check devices every 30 seconds
UNREACHABLE_THRESHOLD = 2  # Number of failed pings before considering device down

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

# Shared data structure to store device status and ping failures
data = {
    "device_status": {}
}
ping_failures = {}  # Track consecutive ping failures

# Track alert times and initial failure times for each device
last_alert_times = {}
initial_failure_times = {}

def can_send_alert(device_name, is_first_alert=False):
    """Check if enough time has passed to send an alert"""
    now = datetime.now()
    
    # For first alert after device goes down
    if is_first_alert:
        if device_name not in initial_failure_times:
            return False
        time_since_failure = now - initial_failure_times[device_name]
        return time_since_failure >= timedelta(minutes=INITIAL_DELAY)
    
    # For subsequent alerts
    if device_name not in last_alert_times:
        return True
    
    time_since_last_alert = now - last_alert_times[device_name]
    return time_since_last_alert >= timedelta(minutes=ALERT_COOLDOWN)

def update_alert_time(device_name):
    """Update the last alert time for a device"""
    last_alert_times[device_name] = datetime.now()

def mark_device_down(device_name):
    """Mark when a device first goes down"""
    if device_name not in initial_failure_times:
        initial_failure_times[device_name] = datetime.now()
        log(f"Device {device_name} marked as down. Initial alert will be sent in {INITIAL_DELAY} minutes")

def reset_device_status(device_name):
    """Reset tracking when a device comes back up"""
    if device_name in initial_failure_times:
        del initial_failure_times[device_name]
    if device_name in last_alert_times:
        del last_alert_times[device_name]

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
                    is_reachable = _is_reachable(device["ip"])
                    
                    # Track consecutive failures
                    if not is_reachable:
                        ping_failures[device["name"]] = ping_failures.get(device["name"], 0) + 1
                        log(f"Ping failure {ping_failures[device['name']]} for {device['name']}")
                    else:
                        ping_failures[device["name"]] = 0
                    
                    # Only consider device down after threshold failures
                    device_down = ping_failures.get(device["name"], 0) >= UNREACHABLE_THRESHOLD
                    alerts = _check_device(device) if device_down else []
                    status = "Alert" if alerts else "OK"
                    
                    # Update device status in data structure
                    data["device_status"][device["name"]] = {
                        "status": status,
                        "messages": alerts,
                        "ip": device["ip"],
                        "reachable": not device_down
                    }
                    
                    # Check if device state changed
                    prev_state = device_alert_state.get(device["name"], {"reachable": True, "alerts": []})
                    state_changed = (not device_down) != prev_state["reachable"]
                    
                    if device_down:
                        # Device is down
                        if state_changed:
                            # Just went down, mark it
                            mark_device_down(device["name"])
                            log(f"Device {device['name']} has gone down after {UNREACHABLE_THRESHOLD} failed pings")
                        
                        # Check if notifications are enabled for this device
                        notifications_enabled = device.get("notifications_enabled", True)
                        if not notifications_enabled:
                            log(f"Skipping alert for {device['name']} - notifications disabled")
                            continue
                        
                        # Check if we should send an alert
                        is_first_alert = device["name"] not in last_alert_times
                        if can_send_alert(device["name"], is_first_alert):
                            alert_msg = f"Device {device['name']} ({device['ip']}) is unreachable"
                            current_alerts.append(alert_msg)
                            log(f"Adding alert: {alert_msg}")
                            update_alert_time(device["name"])
                    else:
                        # Device is up
                        if state_changed and device["name"] in initial_failure_times:
                            # Just came back up
                            log(f"Device {device['name']} has recovered")
                            reset_device_status(device["name"])
                    
                    # Update stored state
                    device_alert_state[device["name"]] = {
                        "reachable": not device_down,
                        "alerts": alerts
                    }
                    
                except Exception as e:
                    log(f"Error processing device {device.get('name', 'unknown')}: {str(e)}")
                    continue
            
            # Send email if there are any alerts
            if current_alerts and _send_alert:
                alert_text = "Network Monitor Alerts:\n\n" + "\n".join(f"- {msg}" for msg in current_alerts)
                if len(current_alerts) > 1:
                    alert_text += f"\n\nNote: Next alerts for these devices will be sent after {ALERT_COOLDOWN/60:.1f} hours if they remain unreachable."
                else:
                    alert_text += f"\n\nNote: Next alert for this device will be sent after {ALERT_COOLDOWN/60:.1f} hours if it remains unreachable."
                _send_alert(alert_text)
            
            time.sleep(PING_INTERVAL)  # Wait before next check
            
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

def save_devices_config(devices):
    """Save devices configuration back to yaml file"""
    config = {"devices": devices}
    with open('/app/config/devices.yaml', 'w') as f:
        yaml.safe_dump(config, f, default_flow_style=False)

@app.route('/api/device-settings', methods=['GET'])
def get_device_settings():
    """Get current device notification settings"""
    try:
        with open('/app/config/devices.yaml') as f:
            devices = yaml.safe_load(f)['devices']
        return jsonify({
            "success": True,
            "devices": [{
                "name": device["name"],
                "notifications_enabled": device.get("notifications_enabled", True)
            } for device in devices]
        })
    except Exception as e:
        log(f"Error getting device settings: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/device-settings', methods=['POST'])
def update_device_settings():
    """Update device notification settings"""
    try:
        updates = request.get_json()
        with open('/app/config/devices.yaml') as f:
            config = yaml.safe_load(f)
            devices = config['devices']
        
        # Update notifications_enabled for each device
        for device in devices:
            if device["name"] in updates:
                device["notifications_enabled"] = updates[device["name"]]
        
        # Save changes back to file
        save_devices_config(devices)
        
        log(f"Updated notification settings: {updates}")
        return jsonify({"success": True})
    except Exception as e:
        log(f"Error updating device settings: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

def start_web_server():
    """Start the web server and background monitoring thread."""
    # Start the background thread
    threading.Thread(target=update_data, daemon=True).start()
    
    # Run the Flask web server
    app.run(host='0.0.0.0', port=PORT)
