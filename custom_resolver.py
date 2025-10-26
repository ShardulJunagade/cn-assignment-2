#!/usr/bin/python3
import socket
import json
from datetime import datetime
import os

# IP Pool - CHANGED to use routable Mininet IPs
IP_POOL = [
    "10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4", "10.0.0.5",
    "10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4", "10.0.0.5",
    "10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4", "10.0.0.5"
]

RULES = {
    "morning": {"start": 4, "end": 11, "pool_start": 0},    # 04:00–11:59
    "afternoon": {"start": 12, "end": 19, "pool_start": 5}, # 12:00–19:59
    "night": {"start": 20, "end": 3, "pool_start": 10}      # 20:00–03:59
}

def select_ip(header):
    hour = int(header[:2])
    query_id = int(header[-2:])  # last 2 chars = ID

    # Find time period
    if 4 <= hour <= 11:
        rule = RULES["morning"]
    elif 12 <= hour <= 19:
        rule = RULES["afternoon"]
    else:
        rule = RULES["night"]

    base = rule["pool_start"]
    ip_index = base + (query_id % 5)
    return IP_POOL[ip_index]

def start_server(host="10.0.0.5", port=9999): # CHANGED host
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((host, port))
    print(f"--- Custom resolver running on {host}:{port} ---")

    while True:
        data, addr = s.recvfrom(4096)
        
        # Protect against empty/short packets
        if len(data) < 8:
            continue
            
        header = data[:8].decode()
        dns_query = data[8:].decode(errors="ignore")
        ip = select_ip(header)

        print(f"[Server Log] Received from {addr}: Header={header}, Query={dns_query}, Resolved={ip}")
        response = f"{header}|{dns_query}|{ip}"
        s.sendto(response.encode(), addr)

start_server()
