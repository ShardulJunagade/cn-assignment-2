#!/usr/bin/python3
import socket
import sys
from datetime import datetime

SERVER_IP = "10.0.0.5"
SERVER_PORT = 9999
QUERY_ID = "01" # Using a static ID (01) for this client

def resolve(domain):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2.0) # 2-second timeout

    # 1. Construct the custom header (HHMMSSID)
    now = datetime.now()
    header_time = now.strftime("%H%M%S")
    header = header_time + QUERY_ID

    # 2. Construct the full message
    message = header + domain
    
    try:
        # 3. Send to server
        s.sendto(message.encode(), (SERVER_IP, SERVER_PORT))

        # 4. Receive response
        data, addr = s.recvfrom(1024)

        # 5. Parse response (header|query|ip)
        response = data.decode()
        parts = response.split('|')
        
        if len(parts) == 3:
            resolved_ip = parts[2]
            print(resolved_ip) # Print just the IP
        else:
            print(f"Error: Received malformed response: {response}")

    except socket.timeout:
        print("Error: Query timed out.")
    finally:
        s.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <domain_name>")
        sys.exit(1)
    
    resolve(sys.argv[1])
