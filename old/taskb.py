#!/usr/bin/env python3
import argparse
import os, csv, time
import socket
from ipaddress import ip_address
from pathlib import Path
import dns.flags
import dns.message
import dns.query
import dns.rcode
import dns.rdatatype


def query_file(label):
    root = Path(__file__).resolve().parent
    return root / "pcap_queries" / f"{label}_queries.csv"

def load_queries(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as h:
        reader = csv.DictReader(h)
        return [r["dns.qry.name"].strip() for r in reader if r.get("dns.qry.name")]

def pcap_stats(path: Path):
    total_bytes = 0
    t_first = None
    t_last = None
    with open(path, "r", encoding="utf-8", errors="ignore") as h:
        reader = csv.DictReader(h)
        for r in reader:
            fl = r.get("frame.len")
            tr = r.get("frame.time_relative")
            if fl:
                try:
                    total_bytes += int(float(fl))
                except Exception:
                    pass
            if tr:
                try:
                    t = float(tr)
                    if t_first is None or t < t_first:
                        t_first = t
                    if t_last is None or t > t_last:
                        t_last = t
                except Exception:
                    pass
    dur = (t_last - t_first) if (t_first is not None and t_last is not None and t_last > t_first) else 0.0
    return total_bytes, dur

def nameservers():
    ns = []
    try:
        with open("/etc/resolv.conf") as h:
            for line in h:
                if line.startswith("nameserver"):
                    ip = line.split()[1]
                    try:
                        ip_obj = ip_address(ip)
                        if not ip_obj.is_loopback and not ip_obj.is_unspecified:
                            ns.append(ip)
                    except ValueError:
                        pass
    except Exception:
        pass
    return ns or ["8.8.8.8", "1.1.1.1"]

def perform_query(servers, domain, timeout, port):
    q = dns.message.make_query(domain, dns.rdatatype.A)
    q.flags |= dns.flags.RD
    last_exc = None
    for s in servers:
        try:
            t0 = time.perf_counter()
            resp = dns.query.udp(q, s, timeout=timeout, port=port)
            dt = (time.perf_counter() - t0) * 1000.0
            status = dns.rcode.to_text(resp.rcode())
            answers = []
            for rrset in resp.answer:
                if rrset.rdtype == dns.rdatatype.A:
                    for r in rrset:
                        answers.append(getattr(r, "address", r.to_text()))
            return status, dt, answers, s
        except Exception as e:
            last_exc = e
            continue
    return ("TIMEOUT" if last_exc else "ERROR"), 0.0, [], (servers[-1] if servers else "")

def write_csv(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as h:
        w = csv.writer(h)
        w.writerow(["domain", "status", "query_time_ms", "resolver_ip", "answers"])
        for r in records:
            w.writerow([r["domain"], r["status"], f'{r["latency_ms"]:.3f}', r["resolver_ip"], ";".join(r["answers"])])

def write_summary(label, path, total, succ, fail, timeouts, cum_ms, dur_s):
    avg = (cum_ms / succ) if succ else 0.0
    thr = (total / dur_s) if dur_s > 0 else 0.0
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as h:
        h.write(f"Total Queries: {total}\n")
        h.write(f"Successful Resolutions: {succ}\n")
        h.write(f"Failed Resolutions: {fail}\n")
        h.write(f"Timeout Failures: {timeouts}\n")
        h.write(f"Average Lookup Latency (ms): {avg:.2f}\n")
        h.write(f"Average Throughput (queries/sec): {thr:.2f}\n")

    compare_csv_path = path.parent / "summary_comparison.csv"
    file_exists = os.path.exists(compare_csv_path)
    with open(compare_csv_path, "a", encoding="utf-8") as h:
        writer = csv.writer(h)
        if not file_exists:
            writer.writerow(["Label", "Total", "Success", "Failure", "Timeouts", "Avg Latency (ms)", "Throughput (qps)", "Throughput (bps)"])
        writer.writerow([label, total, succ, fail, timeouts, avg, thr])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--label")
    p.add_argument("--query-file")
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--port", type=int, default=53)
    p.add_argument("--output-dir", default="results/system")
    args = p.parse_args()
    print(f"Label: {args.label}")
    print(f"Query File: {args.query_file}")

    qpath = Path(args.query_file)
    if not qpath.exists():
        raise SystemExit(f"missing {qpath}")
    domains = load_queries(qpath)
    if not domains:
        raise SystemExit("no queries")

    pcap_bytes, pcap_dur = pcap_stats(qpath)

    resolvers = nameservers()
    out_dir = Path(args.output_dir)
    csv_path = out_dir / f"{args.label}_system_results.csv"
    sum_path = out_dir / f"{args.label}_system_summary.txt"

    recs = []
    ok = 0
    fail = 0
    tout = 0
    cum = 0.0
    t0 = time.perf_counter()
    for d in domains:
        st, ms, ans, rip = perform_query(resolvers, d, args.timeout, args.port)
        if st == "NOERROR" and ans:
            ok += 1
            cum += ms
        else:
            fail += 1
            if st == "TIMEOUT":
                tout += 1
        recs.append({"domain": d, "status": st, "latency_ms": ms, "resolver_ip": rip, "answers": ans})
    dur = time.perf_counter() - t0

    write_csv(csv_path, recs)
    # Calculate bps from PCAP frame.len over PCAP duration; if unavailable, fall back to runtime duration.
    denom = pcap_dur if pcap_dur > 0 else (dur if dur > 0 else 1e-9)
    bps = 8.0 * pcap_bytes / denom

    avg = (cum / ok) if ok else 0.0
    thr = (len(domains) / dur) if dur > 0 else 0.0
    sum_path.parent.mkdir(parents=True, exist_ok=True)
    with open(sum_path, "w", encoding="utf-8") as h:
        h.write(f"Total Queries: {len(domains)}\n")
        h.write(f"Successful Resolutions: {ok}\n")
        h.write(f"Failed Resolutions: {fail}\n")
        h.write(f"Timeout Failures: {tout}\n")
        h.write(f"Average Lookup Latency (ms): {avg:.2f}\n")
        h.write(f"Average Throughput (queries/sec): {thr:.2f}\n")
        h.write(f"Throughput (bps, from PCAP frame.len): {bps:.2f}\n")
        h.write(f"Total Bytes (from PCAP frame.len): {pcap_bytes}\n")

    compare_csv_path = sum_path.parent / "summary_comparison.csv"
    file_exists = os.path.exists(compare_csv_path)
    with open(compare_csv_path, "a", encoding="utf-8") as h:
        writer = csv.writer(h)
        if not file_exists:
            writer.writerow(["Label", "Total", "Success", "Failure", "Timeouts", "Avg Latency (ms)", "Throughput (qps)", "Throughput (bps)"])
        writer.writerow([args.label, len(domains), ok, fail, tout, avg, thr, bps])
    print(f"Results written to {csv_path} and {sum_path}")

if __name__ == "__main__":
    main()
