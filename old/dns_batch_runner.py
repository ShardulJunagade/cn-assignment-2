"""Replay a batch of DNS queries and collect latency/throughput metrics."""

from __future__ import annotations

import argparse
import csv
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple
from ipaddress import ip_address

import dns.exception
import dns.flags
import dns.message
import dns.query
import dns.rcode
import dns.rdatatype
import dns.resolver


@dataclass
class QueryResult:
    domain: str
    status: str
    latency_ms: float
    resolver_ip: str
    recursion_desired: bool
    answers: List[str]


def load_queries(path: Path) -> List[Tuple[str, Optional[bool]]]:
    """Load queries from plain text or tshark CSV with headers.

    Plain text format: one domain per line, optionally ",true|false" to specify recursion.
    Tshark CSV: expects a header with "dns.qry.name" and optionally "dns.flags.recdesired".
    """
    # Peek at the first line to decide how to parse
    with path.open() as h:
        first = h.readline()

    queries: List[Tuple[str, Optional[bool]]] = []
    if "dns.qry.name" in first:
        # Parse as CSV
        import csv as _csv
        with path.open() as h:
            reader = _csv.DictReader(h)
            for row in reader:
                domain = (row.get("dns.qry.name") or "").strip()
                if not domain:
                    continue
                flag_raw = (row.get("dns.flags.recdesired") or "").strip().lower()
                if flag_raw in {"1", "true", "yes"}:
                    recursion_flag = True
                elif flag_raw in {"0", "false", "no"}:
                    recursion_flag = False
                else:
                    recursion_flag = None
                queries.append((domain, recursion_flag))
        return queries

    # Fallback: parse as plain text list
    with path.open() as handle:
        for line in handle:
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            if "," in raw:
                domain_part, flag_part = raw.split(",", 1)
                domain = domain_part.strip()
                flag_token = flag_part.strip().lower()
                if flag_token in {"1", "true", "yes"}:
                    recursion_flag = True
                elif flag_token in {"0", "false", "no"}:
                    recursion_flag = False
                else:
                    recursion_flag = None
            else:
                domain = raw
                recursion_flag = None
            if domain:
                queries.append((domain, recursion_flag))
    return queries


def system_nameservers() -> Sequence[str]:
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
        # Fallback to public resolvers (requires NAT for egress)
        usable = ["8.8.8.8", "1.1.1.1"]
    return tuple(usable)


def perform_query(
    nameservers: Sequence[str],
    domain: str,
    qtype: int,
    recursion_desired: bool,
    timeout: float,
    port: int,
) -> Tuple[str, float, List[str], str]:
    query = dns.message.make_query(domain, qtype)
    if recursion_desired:
        query.flags |= dns.flags.RD
    else:
        query.flags &= ~dns.flags.RD

    last_error: Optional[Exception] = None
    for server in nameservers:
        try:
            start = time.perf_counter()
            response = dns.query.udp(query, server, timeout=timeout, port=port)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            status = dns.rcode.to_text(response.rcode())
            answers: List[str] = []
            for rrset in response.answer:
                if rrset.rdtype == dns.rdatatype.A:
                    answers.extend(getattr(rdata, "address", rdata.to_text()) for rdata in rrset)
                elif rrset.rdtype == dns.rdatatype.AAAA:
                    answers.extend(getattr(rdata, "address", rdata.to_text()) for rdata in rrset)
                else:
                    answers.append(rrset.to_text())
            return status, elapsed_ms, answers, server
        except (dns.exception.Timeout, OSError) as exc:
            last_error = exc
            continue
    status = "TIMEOUT" if isinstance(last_error, dns.exception.Timeout) else "ERROR"
    return status, 0.0, [], nameservers[-1] if nameservers else ""


def write_csv(path: Path, records: Iterable[QueryResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["domain", "status", "query_time_ms", "resolver_ip", "recursion_desired", "answers"])
        for record in records:
            answers = ";".join(record.answers)
            writer.writerow(
                [
                    record.domain,
                    record.status,
                    f"{record.latency_ms:.3f}",
                    record.resolver_ip,
                    "true" if record.recursion_desired else "false",
                    answers,
                ]
            )


def write_summary(
    path: Path,
    total: int,
    successes: int,
    failures: int,
    timeout_failures: int,
    cumulative_latency_ms: float,
    total_duration_s: float,
) -> None:
    avg_latency = (cumulative_latency_ms / successes) if successes else 0.0
    throughput = (total / total_duration_s) if total_duration_s > 0 else 0.0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        handle.write(f"Total Queries: {total}\n")
        handle.write(f"Successful Resolutions: {successes}\n")
        handle.write(f"Failed Resolutions: {failures}\n")
        handle.write(f"Timeout Failures: {timeout_failures}\n")
        handle.write(f"Average Lookup Latency (ms): {avg_latency:.2f}\n")
        handle.write(f"Average Throughput (queries/sec): {throughput:.2f}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="DNS batch runner for CS331 assignment")
    parser.add_argument("query_file", type=Path, help="File containing one domain per line")
    parser.add_argument("--mode", choices=("system", "custom"), default="system", help="Resolver target")
    parser.add_argument("--nameserver", action="append", dest="nameservers", help="Custom resolver IP (can be repeated)")
    parser.add_argument("--port", type=int, default=53, help="Port for the custom resolver (default: 53)")
    parser.add_argument("--timeout", type=float, default=2.0, help="Per-query timeout in seconds")
    parser.add_argument("--recursion", choices=("inherit", "on", "off"), default="inherit", help="Override RD bit handling")
    parser.add_argument("--output-dir", type=Path, default=Path("results"), help="Directory for CSV and summary outputs")
    parser.add_argument("--csv-name", help="Filename for the CSV (default derived from mode and query file)")
    parser.add_argument("--summary-name", help="Filename for the summary text file")
    parser.add_argument("--label", help="Optional label used when deriving default filenames")
    args = parser.parse_args()

    queries = load_queries(args.query_file)
    if not queries:
        raise SystemExit("No queries found in the provided file")

    default_recursion = True if args.mode == "system" else False

    if args.mode == "system":
        target_nameservers: Sequence[str] = system_nameservers()
    else:
        if not args.nameservers:
            raise SystemExit("--nameserver is required when --mode custom is selected")
        target_nameservers = tuple(args.nameservers)

    if args.csv_name:
        csv_path = args.output_dir / args.csv_name
    else:
        base = args.label or args.query_file.stem
        suffix = "system" if args.mode == "system" else "custom"
        csv_path = args.output_dir / f"{base}_{suffix}_results.csv"

    if args.summary_name:
        summary_path = args.output_dir / args.summary_name
    else:
        base = args.label or args.query_file.stem
        suffix = "system" if args.mode == "system" else "custom"
        summary_path = args.output_dir / f"{base}_{suffix}_summary.txt"

    # Informational print to help diagnose TIMEOUTs inside Mininet namespaces
    print(f"[dns_batch_runner] Mode={args.mode} Using nameservers={list(target_nameservers)} Timeout={args.timeout}s Port={args.port}")

    results: List[QueryResult] = []
    total_queries = len(queries)
    success_count = 0
    failure_count = 0
    timeout_failures = 0
    cumulative_latency = 0.0

    start_batch = time.perf_counter()

    for domain, line_flag in queries:
        if args.recursion == "on":
            recursion_desired = True
        elif args.recursion == "off":
            recursion_desired = False
        else:
            recursion_desired = line_flag if line_flag is not None else default_recursion

        status, latency_ms, answers, resolver_ip = perform_query(
            nameservers=target_nameservers,
            domain=domain,
            qtype=dns.rdatatype.A,
            recursion_desired=recursion_desired,
            timeout=args.timeout,
            port=args.port,
        )

        if status == "NOERROR" and answers:
            success_count += 1
            cumulative_latency += latency_ms
        else:
            failure_count += 1
            if status == "TIMEOUT":
                timeout_failures += 1

        results.append(
            QueryResult(
                domain=domain,
                status=status,
                latency_ms=latency_ms,
                resolver_ip=resolver_ip,
                recursion_desired=recursion_desired,
                answers=answers,
            )
        )

    total_duration = time.perf_counter() - start_batch

    write_csv(csv_path, results)
    write_summary(
        summary_path,
        total=total_queries,
        successes=success_count,
        failures=failure_count,
        timeout_failures=timeout_failures,
        cumulative_latency_ms=cumulative_latency,
        total_duration_s=total_duration,
    )


if __name__ == "__main__":
    main()
