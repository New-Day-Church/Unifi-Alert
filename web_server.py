from flask import Flask, jsonify, render_template
import threading
import time
import yaml
import os
from datetime import datetime

# Initialize Flask app
app = Flask(__name__, 
    template_folder=os.path.join(os.path.dirname(__file__), 'templates'))

# These will be initialized by init_monitor
_check_device = None
_is_reachable = None

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

def init_monitor(check_device, is_reachable):
    """Initialize the monitor with required functions."""
    global _check_device, _is_reachable
    _check_device = check_device
    _is_reachable = is_reachable

def update_data():
    """Background thread to update device status data."""
    while True:
        try:
            # Load devices from yaml config
            with open('/app/config/devices.yaml') as f:
                devices = yaml.safe_load(f)['devices']
            
            for device in devices:
                try:
                    # Check device status
                    alerts = _check_device(device)
                    status = "Alert" if alerts else "OK"
                    data["device_status"][device["name"]] = {
                        "status": status,
                        "messages": alerts,
                        "ip": device["ip"],
                        "reachable": _is_reachable(device["ip"])
                    }
                except Exception as e:
                    log(f"Error processing device {device.get('name', 'unknown')}: {str(e)}")
                    continue
            
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
    app.run(host='0.0.0.0', port=5000)
