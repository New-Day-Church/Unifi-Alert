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
_check_unifi_switch = None
_get_snmp_data = None
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

app = Flask(__name__)

# Shared data structure to store SNMP and IP status
data = {
    "snmp_info": {},
    "ip_status": {}
}

def init_monitor(check_unifi_switch, get_snmp_data, is_reachable):
    """Initialize the monitor with required functions."""
    global _check_unifi_switch, _get_snmp_data, _is_reachable
    _check_unifi_switch = check_unifi_switch
    _get_snmp_data = get_snmp_data
    _is_reachable = is_reachable

def update_data():
    """Background thread to update SNMP and IP status data."""
    while True:
        try:
            # Load devices from yaml config
            with open('/app/config/devices.yaml') as f:
                devices = yaml.safe_load(f)['devices']
            
            for device in devices:
                try:
                    if device['type'] == 'ping':
                        # Update IP reachability status
                        data["ip_status"][device["name"]] = "Reachable" if _is_reachable(device["ip"]) else "Unreachable"
                    elif device['type'] == 'unifi_switch':
                        # Check UniFi switch metrics
                        alerts = _check_unifi_switch(device)
                        if alerts:
                            data["snmp_info"][device["name"]] = {"status": "Alert", "messages": alerts}
                        else:
                            data["snmp_info"][device["name"]] = {"status": "OK", "messages": []}
                except Exception as e:
                    log(f"Error processing device {device.get('name', 'unknown')}: {str(e)}")
                    continue
            
            time.sleep(5)  # Update every 5 seconds
            
        except Exception as e:
            log(f"Error in update thread: {str(e)}")
            time.sleep(10)  # Wait longer on error before retry
        
        for device in devices:
            # Update SNMP information
            snmp_value = get_snmp_data(device, device["oid"])
            data["snmp_info"][device["name"]] = snmp_value if snmp_value is not None else "Unavailable"
            
            # Update IP reachability status
            data["ip_status"][device["name"]] = "Reachable" if is_reachable(device["ip"]) else "Unreachable"
        
        time.sleep(5)  # Update every 5 seconds

@app.route('/api/data')
def api_data():
    """API endpoint to return SNMP and IP status data as JSON."""
    return jsonify(data)

@app.route('/')
def index():
    """Serve the main webpage."""
    return render_template('index.html')

if __name__ == '__main__':
    # Start the background thread
    threading.Thread(target=update_data, daemon=True).start()
    
    # Run the Flask web server on a unique port (e.g., 5000)
    app.run(host='0.0.0.0', port=5000)
