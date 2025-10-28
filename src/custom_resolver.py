#!/usr/bin/env python3
"""Custom DNS resolver with logging, caching, and optional recursion."""

from __future__ import annotations

import argparse
import csv
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import dns.exception
import dns.flags
import dns.message
import dns.name
import dns.query
import dns.rcode
import dns.rdatatype
import dns.resolver
from ipaddress import ip_address

ROOT_SERVERS: Tuple[str, ...] = (
    "198.41.0.4",
    "199.9.14.201",
    "192.33.4.12",
    "199.7.91.13",
    "192.203.230.10",
    "192.5.5.241",
    "192.112.36.4",
    "198.97.190.53",
    "192.36.148.17",
    "192.58.128.30",
    "193.0.14.129",
    "199.7.83.42",
    "202.12.27.33",
)


@dataclass
class CacheEntry:
    rrsets: List[dns.rrset.RRset]
    expiry: float

    def fresh(self) -> bool:
        return time.time() < self.expiry


@dataclass
class TraceEvent:
    server: str
    step: str
    response: str
    rtt: float
    total_time: float
    cache_status: str
    event_time: float


class ResolverLogger:
    """Thread-safe CSV logger for resolver activity."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._lock = threading.Lock()
        self._file = path.open("a", newline="")
        self._writer = csv.writer(self._file)
        if self._file.tell() == 0:
            self._writer.writerow(
                [
                    "timestamp",
                    "domain",
                    "mode",
                    "server_contacted",
                    "step",
                    "response_or_referral",
                    "rtt_s",
                    "total_time_s",
                    "cache_status",
                    "request_id",
                ]
            )
            self._file.flush()

    def log_event(self, domain: str, mode: str, event: TraceEvent, request_id: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(event.event_time))
        with self._lock:
            self._writer.writerow(
                [
                    timestamp,
                    domain,
                    mode,
                    event.server,
                    event.step,
                    event.response,
                    f"{event.rtt:.6f}",
                    f"{event.total_time:.6f}",
                    event.cache_status,
                    request_id,
                ]
            )
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            self._file.close()


class ResolverServer:
    """Minimal DNS resolver that performs iterative lookups and logs every step."""

    def __init__(
        self,
        listen_ip: str,
        listen_port: int,
        timeout: float,
        cache_enabled: bool,
        recursive_default: bool,
        logger: ResolverLogger,
        root_servers: Sequence[str],
    ) -> None:
        self.listen_ip = listen_ip
        self.listen_port = listen_port
        self.timeout = timeout
        self.cache_enabled = cache_enabled
        self.recursive_default = recursive_default
        self.logger = logger
        self.root_servers = list(root_servers)

        self._cache: Dict[Tuple[str, int], CacheEntry] = {}
        self._cache_lock = threading.Lock()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._shutdown = threading.Event()

    # --- Helper for safe upstream resolvers ---------------------------
    def _safe_system_nameservers(self) -> Sequence[str]:
        """Return non-loopback, non-unspecified nameservers with sensible fallback.

        Inside Mininet namespaces, 127.0.0.53 is not reachable; prefer public resolvers if needed.
        """
        resolver = dns.resolver.Resolver(configure=True)
        candidates = list(resolver.nameservers) if resolver.nameservers else []
        usable: List[str] = []
        for ns in candidates:
            try:
                ip = ip_address(ns)
                if ip.is_loopback or ip.is_unspecified:
                    continue
                usable.append(ns)
            except ValueError:
                # Not an IP literal; skip
                continue
        if not usable:
            usable = ["8.8.8.8", "1.1.1.1"]
        return tuple(usable)

    # --- Cache helpers -------------------------------------------------
    def _cache_key(self, qname: str, qtype: int) -> Tuple[str, int]:
        return qname.lower(), qtype

    def _cache_lookup(self, qname: str, qtype: int) -> Optional[List[dns.rrset.RRset]]:
        key = self._cache_key(qname, qtype)
        with self._cache_lock:
            entry = self._cache.get(key)
            if not entry:
                return None
            if entry.fresh():
                # Return shallow copies so TTL counters remain intact.
                copies: List[dns.rrset.RRset] = []
                for rrset in entry.rrsets:
                    if hasattr(rrset, "copy"):
                        try:
                            copies.append(rrset.copy())
                            continue
                        except Exception:
                            pass
                    copies.append(rrset)
                return copies
            self._cache.pop(key, None)
            return None

    def _cache_store(self, qname: str, qtype: int, rrsets: List[dns.rrset.RRset]) -> None:
        if not self.cache_enabled:
            return
        ttl_values: List[int] = []
        for rrset in rrsets:
            # TTL is a property of the RRset, not individual RDATA items.
            ttl = getattr(rrset, "ttl", None)
            if isinstance(ttl, (int, float)):
                ttl_values.append(int(ttl))
        if not ttl_values:
            return
        ttl = min(ttl_values)
        if ttl <= 0:
            return
        expiry = time.time() + ttl
        key = self._cache_key(qname, qtype)
        with self._cache_lock:
            stored: List[dns.rrset.RRset] = []
            for rrset in rrsets:
                if hasattr(rrset, "copy"):
                    try:
                        stored.append(rrset.copy())
                        continue
                    except Exception:
                        pass
                stored.append(rrset)
            self._cache[key] = CacheEntry(stored, expiry)

    # --- Resolution pipeline -------------------------------------------
    def _query_server(
        self,
        server_ip: str,
        qname: str,
        qtype: int,
        recursion_desired: bool,
    ) -> Tuple[dns.message.Message, float]:
        query = dns.message.make_query(qname, qtype)
        if recursion_desired:
            query.flags |= dns.flags.RD
        else:
            query.flags &= ~dns.flags.RD
        start = time.perf_counter()
        response = dns.query.udp(query, server_ip, timeout=self.timeout)
        rtt = time.perf_counter() - start
        return response, rtt

    def _step_name(self, depth: int) -> str:
        if depth == 0:
            return "Root"
        if depth == 1:
            return "TLD"
        return "Authoritative"

    def _summarize(self, response: dns.message.Message) -> str:
        rcode = response.rcode()
        if rcode == dns.rcode.NXDOMAIN:
            return "NXDOMAIN"
        if response.answer:
            return "ANSWER"
        if response.authority:
            ns_names = ",".join(sorted({rr.to_text() for rrset in response.authority for rr in rrset}))
            return f"REFERRAL {ns_names}" if ns_names else "REFERRAL"
        return dns.rcode.to_text(rcode)

    def _extract_glue_ips(self, response: dns.message.Message) -> List[str]:
        ips: List[str] = []
        for rrset in response.additional:
            if rrset.rdtype not in (dns.rdatatype.A, dns.rdatatype.AAAA):
                continue
            for rr in rrset:
                address = getattr(rr, "address", rr.to_text())
                ips.append(address)
        return ips

    def _extract_ns_names(self, response: dns.message.Message) -> List[str]:
        names: List[str] = []
        for rrset in response.authority:
            if rrset.rdtype != dns.rdatatype.NS:
                continue
            for rr in rrset:
                names.append(rr.target.to_text())
        return names

    def _resolve_ns_addresses(self, ns_names: Iterable[str]) -> List[str]:
        resolver = dns.resolver.Resolver(configure=True)
        resolver.lifetime = self.timeout
        safe_ns = self._safe_system_nameservers()
        if safe_ns:
            resolver.nameservers = list(safe_ns)
        ips: List[str] = []
        for ns_name in ns_names:
            try:
                answer = resolver.resolve(ns_name, rdtype=dns.rdatatype.A, raise_on_no_answer=False)
            except (dns.resolver.NXDOMAIN, dns.exception.Timeout, dns.resolver.NoNameservers):
                continue
            for rrset in answer.response.answer:
                if rrset.rdtype != dns.rdatatype.A:
                    continue
                for rr in rrset:
                    address = getattr(rr, "address", rr.to_text())
                    ips.append(address)
        return ips

    def _recursive_lookup(self, qname: str, qtype: int) -> Tuple[List[dns.rrset.RRset], int, List[TraceEvent]]:
        """Perform a recursive resolution using the system resolvers (public if needed)."""
        resolver = dns.resolver.Resolver(configure=True)
        resolver.lifetime = self.timeout
        safe_ns = self._safe_system_nameservers()
        if safe_ns:
            resolver.nameservers = list(safe_ns)

        trace: List[TraceEvent] = []
        start = time.perf_counter()
        try:
            # raise_on_no_answer=False so we can inspect response even if empty
            answer = resolver.resolve(qname, rdtype=qtype, raise_on_no_answer=False)
            response = answer.response
            rcode = response.rcode()
            total = time.perf_counter() - start
            # We don't have per-hop RTT in this mode; log a single event
            server_logged = resolver.nameservers[0] if resolver.nameservers else "SYSTEM"
            summary = "ANSWER" if response.answer else dns.rcode.to_text(rcode)
            trace.append(
                TraceEvent(
                    server=server_logged,
                    step="Recursive",
                    response=summary,
                    rtt=total,
                    total_time=total,
                    cache_status="MISS",
                    event_time=time.time(),
                )
            )
            return list(response.answer), rcode, trace
        except (dns.exception.Timeout, dns.resolver.NXDOMAIN):
            total = time.perf_counter() - start
            server_logged = resolver.nameservers[0] if resolver.nameservers else "SYSTEM"
            trace.append(
                TraceEvent(
                    server=server_logged,
                    step="Recursive",
                    response="TIMEOUT_OR_NXDOMAIN",
                    rtt=total,
                    total_time=total,
                    cache_status="MISS",
                    event_time=time.time(),
                )
            )
            # If NXDOMAIN, return NXDOMAIN; on timeout, return SERVFAIL
            return [], dns.rcode.NXDOMAIN, trace

    def _iterative_lookup(
        self,
        qname: str,
        qtype: int,
        recursion_desired: bool,
    ) -> Tuple[List[dns.rrset.RRset], int, List[TraceEvent]]:
        trace: List[TraceEvent] = []
        start = time.perf_counter()
        servers: List[str] = list(self.root_servers)
        depth = 0
        last_rcode = dns.rcode.SERVFAIL

        while servers:
            step_name = self._step_name(depth)
            depth = min(depth + 1, 2)
            for server in servers:
                try:
                    response, rtt = self._query_server(server, qname, qtype, recursion_desired)
                except (dns.exception.Timeout, OSError):
                    continue

                last_rcode = response.rcode()
                summary = self._summarize(response)
                total = time.perf_counter() - start
                trace.append(
                    TraceEvent(
                        server=server,
                        step=step_name,
                        response=summary,
                        rtt=rtt,
                        total_time=total,
                        cache_status="MISS",
                        event_time=time.time(),
                    )
                )

                if last_rcode == dns.rcode.NOERROR and response.answer:
                    return list(response.answer), dns.rcode.NOERROR, trace
                if last_rcode == dns.rcode.NXDOMAIN:
                    return [], dns.rcode.NXDOMAIN, trace

                glue_ips = self._extract_glue_ips(response)
                if glue_ips:
                    servers = glue_ips
                    break

                ns_names = self._extract_ns_names(response)
                if not ns_names:
                    continue

                resolved_ips = self._resolve_ns_addresses(ns_names)
                if resolved_ips:
                    servers = resolved_ips
                    break
            else:
                break

        return [], last_rcode, trace

    def resolve(self, qname: str, qtype: int, recursion_requested: bool) -> Tuple[List[dns.rrset.RRset], int, List[TraceEvent], bool]:
        cached = self._cache_lookup(qname, qtype)
        if cached is not None:
            event = TraceEvent(
                server="CACHE",
                step="CACHE",
                response="ANSWER_FROM_CACHE",
                rtt=0.0,
                total_time=0.0,
                cache_status="HIT",
                event_time=time.time(),
            )
            return cached, dns.rcode.NOERROR, [event], True

        # If recursion is requested, try recursive resolution first.
        if recursion_requested:
            answers, rcode, trace = self._recursive_lookup(qname, qtype)
            if answers and rcode == dns.rcode.NOERROR:
                self._cache_store(qname, qtype, answers)
                return answers, rcode, trace, False
            # fall back to iterative if recursive attempt didn't yield an answer
        answers, rcode, trace = self._iterative_lookup(qname, qtype, recursion_requested)
        if answers and rcode == dns.rcode.NOERROR:
            self._cache_store(qname, qtype, answers)
        return answers, rcode, trace, False

    # --- Networking layer ---------------------------------------------
    def serve(self) -> None:
        self._socket.bind((self.listen_ip, self.listen_port))
        print(f"--- Custom resolver running on {self.listen_ip}:{self.listen_port} (cache={'on' if self.cache_enabled else 'off'}, recursive_default={'on' if self.recursive_default else 'off'})")
        try:
            while not self._shutdown.is_set():
                try:
                    data, addr = self._socket.recvfrom(2048)
                except OSError:
                    break
                threading.Thread(target=self._handle_request, args=(data, addr), daemon=True).start()
        finally:
            self._socket.close()

    def shutdown(self) -> None:
        self._shutdown.set()
        try:
            self._socket.close()
        except OSError:
            pass

    def _handle_request(self, data: bytes, addr: Tuple[str, int]) -> None:
        try:
            request = dns.message.from_wire(data)
        except Exception:
            return

        if not request.question:
            return

        question = request.question[0]
        qname = question.name.to_text()
        qtype = question.rdtype
        recursion_requested = bool(request.flags & dns.flags.RD) or self.recursive_default

        answers, rcode, trace, cache_hit = self.resolve(qname, qtype, recursion_requested)
        response = dns.message.make_response(request)

        if answers:
            for rrset in answers:
                response.answer.append(rrset)
        response.set_rcode(rcode)
        if recursion_requested:
            response.flags |= dns.flags.RA

        mode = "recursive" if recursion_requested else "iterative"
        request_id = str(uuid.uuid4())
        for event in trace:
            cache_status = event.cache_status
            if cache_hit:
                cache_status = "HIT"
            self.logger.log_event(qname, mode, TraceEvent(
                server=event.server,
                step=event.step,
                response=event.response,
                rtt=event.rtt,
                total_time=event.total_time,
                cache_status=cache_status,
                event_time=event.event_time,
            ), request_id)

        try:
            self._socket.sendto(response.to_wire(), addr)
        except OSError:
            pass

    def close(self) -> None:
        self.logger.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Custom DNS resolver with logging for CS331 Assignment 2")
    parser.add_argument("--listen", default="10.0.0.5", help="IP address to bind (default: 10.0.0.5)")
    parser.add_argument("--port", type=int, default=53, help="UDP port to listen on (default: 53)")
    parser.add_argument("--timeout", type=float, default=3.0, help="Timeout for upstream DNS queries in seconds")
    parser.add_argument("--log", default="logs/dns_iterative.csv", help="CSV log file path")
    parser.add_argument("--recursive", action="store_true", help="Force recursion even when clients do not request it")
    parser.add_argument("--no-cache", action="store_true", help="Disable the in-memory resolver cache")
    parser.add_argument("--root-server", action="append", dest="roots", help="Override default root server list (can be provided multiple times)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    log_path = Path(args.log)
    logger = ResolverLogger(log_path)

    roots: Sequence[str] = tuple(args.roots) if args.roots else ROOT_SERVERS

    server = ResolverServer(
        listen_ip=args.listen,
        listen_port=args.port,
        timeout=args.timeout,
        cache_enabled=not args.no_cache,
        recursive_default=args.recursive,
        logger=logger,
        root_servers=roots,
    )

    try:
        server.serve()
    except KeyboardInterrupt:
        print("\n--- Resolver stopping (CTRL-C received)")
    finally:
        server.shutdown()
        server.close()


if __name__ == "__main__":
    main()
