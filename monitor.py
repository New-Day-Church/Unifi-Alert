import subprocess
import smtplib
import os
import time
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import yaml
from pysnmp.hlapi import (
    getCmd, SnmpEngine, CommunityData, UdpTransportTarget,
    ContextData, ObjectType, ObjectIdentity
)
from flask import Flask, jsonify, render_template
import threading

# Load email configuration from yaml file
with open('/app/config/email.yaml') as f:
    email_config = yaml.safe_load(f)['smtp']
    
smtp_server = email_config['server']
smtp_port = email_config['port']
sender_email = email_config['sender']
recipient_email = email_config['recipient']

# Email credentials should be set via environment variable for security
sender_password = os.environ.get('EMAIL_PASSWORD')
if not sender_password:
    log("Warning: EMAIL_PASSWORD environment variable not set")

# SNMP Configuration
SNMP_PORT = 161
SNMP_TIMEOUT = 3  # seconds
SNMP_RETRIES = 3  # Number of retries for SNMP queries
MAX_RETRY_DELAY = 5  # Maximum delay between retries in seconds

# Setup logging
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

def get_snmp_data(device, oid):
    """Get SNMP data with proper syntax and error handling with retries"""
    retry_count = 0
    while retry_count < SNMP_RETRIES:
        try:
            # Create SNMP request
            iterator = getCmd(
                SnmpEngine(),
                CommunityData(device['snmp_community']),
                UdpTransportTarget((device['ip'], SNMP_PORT), timeout=SNMP_TIMEOUT),
                ContextData(),
                ObjectType(ObjectIdentity(oid))
            )

            # Get response with fallback values
            error_indication, error_status, error_index, var_binds = next(iterator, (None, None, None, None))
            
            if error_indication:
                log(f"SNMP error for {device['name']} (attempt {retry_count + 1}/{SNMP_RETRIES}): {error_indication}")
            elif error_status:
                log(f"SNMP error status for {device['name']} (attempt {retry_count + 1}/{SNMP_RETRIES}): {error_status}")
            else:
                return int(var_binds[0][1]) if var_binds else None
                
            # Exponential backoff for retries
            if retry_count < SNMP_RETRIES - 1:
                delay = min(SNMP_TIMEOUT * (2 ** retry_count), MAX_RETRY_DELAY)
                time.sleep(delay)
            
        except Exception as e:
            log(f"SNMP exception for {device['name']} (attempt {retry_count + 1}/{SNMP_RETRIES}): {str(e)}")
            if retry_count < SNMP_RETRIES - 1:
                delay = min(SNMP_TIMEOUT * (2 ** retry_count), MAX_RETRY_DELAY)
                time.sleep(delay)
                
        retry_count += 1
    
    return None

def check_unifi_switch(device):
    """Check UniFi switch metrics"""
    alerts = []
    
    # 1. Check standard interface traffic
    for if_name, oid in device.get('interfaces', {}).items():
        octets = get_snmp_data(device, oid)
        if octets is None:
            alerts.append(f"SNMP failed for {if_name}")
            continue
        
        # Calculate utilization (example - adjust for your needs)
        if_speed = 1000000000  # 1Gbps in bits
        utilization = (octets * 8) / if_speed * 100  # Simplified calculation
        
        if utilization > device.get('traffic_threshold', 80):
            alerts.append(f"High traffic on {if_name}: {utilization:.2f}%")

    # 2. Check UniFi CPU/Memory
    cpu = get_snmp_data(device, '1.3.6.1.4.1.4413.1.1.1.1.4.0')
    if cpu and cpu > device.get('cpu_threshold', 80):
        alerts.append(f"High CPU: {cpu}%")
    
    return alerts

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

def send_alert(message):
    """Send email alerts (original working version)"""
    msg = MIMEText(message)
    msg['Subject'] = "Network Alert"
    msg['From'] = sender_email
    msg['To'] = recipient_email

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        log("Alert email sent")
    except Exception as e:
        log(f"Email failed: {str(e)}")

def main():
    log("Starting monitor with SNMP support")
    
    # Import web server after logging is set up
    from web_server import start_web_server, init_monitor
    
    # Initialize the web server with our monitoring functions
    init_monitor(check_unifi_switch=check_unifi_switch,
                get_snmp_data=get_snmp_data,
                is_reachable=is_reachable)
    
    # Start the web server (this will block)
    start_web_server()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        log("Service stopped by user")
    except Exception as e:
        log(f"Fatal error: {str(e)}")
        raise