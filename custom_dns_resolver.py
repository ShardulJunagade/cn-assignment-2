#!/usr/bin/env python3
import socket, struct, time, datetime, random

# --- Root servers (subset) ---
ROOT_SERVERS = [
    "198.41.0.4", "199.9.14.201", "192.33.4.12", "199.7.91.13",
    "192.203.230.10", "192.5.5.241", "192.112.36.4", "198.97.190.53"
]

CACHE = {}
CACHE_TTL = 300  # seconds
LOG_FILE = "dns_server.log"

# -----------------------------------------------------
#  Utilities
# -----------------------------------------------------
def log_entry(domain, mode, client_ip, step, server_ip, response, rtt, total_time, cache_status):
    with open(LOG_FILE, "a") as f:
        f.write(
            f"{datetime.datetime.utcnow().isoformat()},{domain},{mode},{client_ip},"
            f"{step},{server_ip},{response},{round(rtt,2)}ms,{round(total_time,2)}ms,{cache_status}\n"
        )

def build_query(domain):
    tid = random.randint(0, 65535)
    header = struct.pack("!HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    qname = b"".join(bytes([len(x)]) + x.encode() for x in domain.split(".")) + b"\x00"
    question = qname + struct.pack("!HH", 1, 1)
    return tid, header + question

def parse_response(data):
    """Return tuple (A_record_IPs, next_NS_names)."""
    ips, nss = [], []
    try:
        ancount = struct.unpack("!H", data[6:8])[0]
        nscount = struct.unpack("!H", data[8:10])[0]
        arcount = struct.unpack("!H", data[10:12])[0]
        total = ancount + nscount + arcount
        if total == 0:
            return [], []

        offset = 12
        # skip QNAME
        while data[offset] != 0:
            offset += data[offset] + 1
        offset += 5  # null + QTYPE/QCLASS

        for _ in range(total):
            if data[offset] & 0xC0 == 0xC0:
                offset += 2
            else:
                while data[offset] != 0:
                    offset += data[offset] + 1
                offset += 1

            rtype, rclass, ttl, rdlength = struct.unpack("!HHIH", data[offset:offset+10])
            offset += 10
            rdata = data[offset:offset+rdlength]
            offset += rdlength

            if rtype == 1 and rdlength == 4:
                ips.append(".".join(map(str, rdata)))
            elif rtype == 2:  # NS
                ns = []
                i = 0
                while i < len(rdata) and rdata[i] != 0:
                    if rdata[i] & 0xC0 == 0xC0:
                        break
                    l = rdata[i]
                    ns.append(rdata[i+1:i+1+l].decode(errors="ignore"))
                    i += l + 1
                nss.append(".".join(ns))
    except Exception:
        pass
    return ips, nss

# -----------------------------------------------------
#  Core iterative resolver
# -----------------------------------------------------
def iterative_resolve(domain, client_ip):
    if domain in CACHE and CACHE[domain][1] > time.time():
        ip = CACHE[domain][0]
        log_entry(domain, "Iterative", client_ip, "Cache", ip, ip, 0, 0, "HIT")
        return ip

    start_total = time.time()
    current_servers = ROOT_SERVERS[:]
    step = "Root"
    for depth in range(3):  # Root -> TLD -> Authoritative
        server_ip = current_servers[0]
        tid, packet = build_query(domain)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3)
        step_start = time.time()

        try:
            sock.sendto(packet, (server_ip, 53))
            data, _ = sock.recvfrom(4096)
            rtt = (time.time() - step_start) * 1000
            ips, nss = parse_response(data)
        except Exception:
            sock.close()
            log_entry(domain, "Iterative", client_ip, step, server_ip, "TIMEOUT", 0, (time.time() - start_total)*1000, "MISS")
            return None
        sock.close()

        # A record found
        if ips:
            total_time = (time.time() - start_total)*1000
            CACHE[domain] = (ips[0], time.time() + CACHE_TTL)
            log_entry(domain, "Iterative", client_ip, step, server_ip, ips[0], rtt, total_time, "MISS")
            return ips[0]

        # NS referral found
        if nss:
            step = "TLD" if depth == 0 else "Authoritative"
            next_servers = []
            for ns in nss:
                try:
                    ns_ip = socket.gethostbyname(ns)
                    next_servers.append(ns_ip)
                except Exception:
                    continue
            if not next_servers:
                log_entry(domain, "Iterative", client_ip, step, server_ip, "Referral w/ no A", rtt, (time.time()-start_total)*1000, "MISS")
                return None
            current_servers = next_servers
            log_entry(domain, "Iterative", client_ip, step, server_ip, ",".join(nss), rtt, (time.time()-start_total)*1000, "MISS")
            continue

    total_time = (time.time() - start_total)*1000
    log_entry(domain, "Iterative", client_ip, step, "N/A", "Unresolved", 0, total_time, "MISS")
    return None

# -----------------------------------------------------
#  UDP listener
# -----------------------------------------------------
def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("10.0.0.5", 53))
    print("[+] Custom DNS Resolver running on 10.0.0.5:53 ...")

    while True:
        data, addr = sock.recvfrom(1024)
        client_ip, client_port = addr
        domain = None
        try:
            i = 12
            parts = []
            while data[i] != 0:
                l = data[i]; parts.append(data[i+1:i+1+l].decode()); i += l+1
            domain = ".".join(parts)
        except Exception:
            pass
        if not domain:
            continue

        ip = iterative_resolve(domain, client_ip)
        if not ip:
            continue

        # Build a minimal DNS reply
        tid = data[:2]
        flags = b"\x81\x80"  # standard response, recursion available
        qdcount = b"\x00\x01"
        ancount = b"\x00\x01"
        nscount = arcount = b"\x00\x00"
        header = tid + flags + qdcount + ancount + nscount + arcount
        # copy question
        i = 12
        while data[i] != 0:
            i += data[i] + 1
        question = data[12:i+5]
        answer = b"\xc0\x0c" + struct.pack("!HHI", 1, 1, 60) + struct.pack("!H", 4)
        answer += bytes(map(int, ip.split(".")))
        sock.sendto(header + question + answer, addr)

if __name__ == "__main__":
    main()
