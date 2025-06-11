import subprocess
import smtplib
import os
import time
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import yaml
from flask import Flask, jsonify, render_template
import threading

def log(message):
    """Logging function"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] {message}"
    print(log_entry)
    
    # Get log directory from environment or use default
    log_dir = os.environ.get('LOG_DIR', '/app/logs')
    
    # Ensure log directory exists
    os.makedirs(log_dir, exist_ok=True)
    
    with open(os.path.join(log_dir, 'network_monitor.log'), 'a') as f:
        f.write(log_entry + '\n')

# Load email configuration from yaml file
try:
    with open('/app/config/email.yaml') as f:
        email_config = yaml.safe_load(f)['smtp']
    log(f"Email configuration loaded: server={email_config['server']}, port={email_config['port']}, sender={email_config['sender']}")
except Exception as e:
    log(f"Error loading email configuration: {str(e)}")
    raise

smtp_server = email_config['server']
smtp_port = email_config['port']
sender_email = email_config['sender']
recipient_email = email_config['recipient']

# Email credentials should be set via environment variable for security
sender_password = os.environ.get('EMAIL_PASSWORD')
if not sender_password:
    log("Warning: EMAIL_PASSWORD environment variable not set")
else:
    log("EMAIL_PASSWORD environment variable is set")

def is_reachable(ip):
    """Check if a device is reachable via ping."""
    try:
        response = subprocess.run(
            ['ping', '-c', '1', '-W', '1', ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return response.returncode == 0
    except Exception as e:
        log(f"Ping check failed for {ip}: {str(e)}")
        return False

def check_device(device):
    """Check device availability"""
    alerts = []
    
    if not is_reachable(device['ip']):
        alerts.append(f"Device {device['name']} ({device['ip']}) is unreachable")
    
    return alerts

def send_alert(message):
    """Send email alerts"""
    log(f"Attempting to send alert email to {recipient_email}")
    log(f"Email content: {message}")
    
    msg = MIMEText(message)
    msg['Subject'] = "Network Alert"
    msg['From'] = sender_email
    msg['To'] = recipient_email

    try:
        log(f"Connecting to SMTP server {smtp_server}:{smtp_port}")
        server = smtplib.SMTP(smtp_server, smtp_port)
        log("Starting TLS")
        server.starttls()
        log("Logging in to SMTP server")
        server.login(sender_email, sender_password)
        log("Sending message")
        server.send_message(msg)
        server.quit()
        log("Alert email sent successfully")
    except Exception as e:
        log(f"Email failed - Full error: {str(e)}")
        # Print more details about the error
        import traceback
        log(f"Error traceback: {traceback.format_exc()}")

def main():
    log("Starting monitor")
    
    # Send startup notification
    startup_message = "Network Monitor System has started\n\nTime: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    send_alert(startup_message)
    
    # Import web server after logging is set up
    from web_server import start_web_server, init_monitor
    
    # Initialize the web server with our monitoring functions
    init_monitor(check_device=check_device,
                is_reachable=is_reachable,
                send_alert=send_alert)
    
    # Start the web server (this will block)
    start_web_server()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        log("Service stopping gracefully...")
        # Give time for pending operations to complete
        time.sleep(1)
        log("Service stopped by user")
    except Exception as e:
        log(f"Fatal error: {str(e)}")
        # Give time for the error to be logged
        time.sleep(0.5)
        raise