#!/usr/bin/env python3
import csv
import os
import socket
import time
import statistics

def resolve_domains(csv_path: str, output_path: str):
    results = []
    total_queries = 0
    success_count = 0
    failure_count = 0
    latencies = []
    total_bytes = 0  # sum of frame.len for successful queries

    # Start measuring total runtime
    experiment_start = time.time()

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            domain = row["dns.qry.name"].strip()
            frame_len = float(row["frame.len"]) if row["frame.len"] else 0

            if not domain:
                continue
            total_queries += 1

            start_time = time.time()
            try:
                socket.gethostbyname(domain)
                latency = (time.time() - start_time) * 1000  # in ms
                success_count += 1
                latencies.append(latency)
                total_bytes += frame_len
                results.append((domain, "SUCCESS", latency, frame_len))
            except Exception:
                latency = (time.time() - start_time) * 1000
                failure_count += 1
                results.append((domain, "FAILED", latency, frame_len))

    experiment_end = time.time()
    total_duration = experiment_end - experiment_start  # seconds

    # --- Compute metrics ---
    avg_latency = statistics.mean(latencies) if latencies else 0
    avg_throughput_qps = total_queries / total_duration if total_duration > 0 else 0
    total_bits = total_bytes * 8
    throughput_bps = total_bits / total_duration if total_duration > 0 else 0

    summary = {
        "total_queries": total_queries,
        "success_count": success_count,
        "failure_count": failure_count,
        "avg_latency_ms": round(avg_latency, 3),
        "avg_throughput_qps": round(avg_throughput_qps, 3),
        "total_bytes": round(total_bytes, 3),
        "throughput_bps": round(throughput_bps, 3),
    }

    # --- Save detailed results ---
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(["domain", "status", "latency_ms", "frame_len"])
        writer.writerows(results)

    # --- Print summary ---
    print(f"\n=== Results for {csv_path} ===")
    for k, v in summary.items():
        print(f"{k}: {v}")
    
    comparion_csv_path = os.path.join(os.path.dirname(output_path), "summary_comparison.csv")
    file_exists = os.path.exists(comparion_csv_path)
    with open(comparion_csv_path, "a", newline="") as h:
        writer = csv.writer(h)
        if not file_exists:
            writer.writerow(["Label", "Total Queries", "Success Count", "Failure Count", "Avg Latency (ms)", "Avg Throughput (qps)", "Total Bytes", "Throughput (bps)"])
        writer.writerow([
            os.path.basename(output_path),
            total_queries,
            success_count,
            failure_count,
            round(avg_latency, 3),
            round(avg_throughput_qps, 3),
            round(total_bytes, 3),
            round(throughput_bps, 3),
        ])
        
    print(f"Detailed log saved to {output_path}\n")

    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Resolve domains using system DNS resolver")
    parser.add_argument("--input", required=True, help="Path to input CSV of queries")
    parser.add_argument("--output", required=True, help="Path to save results CSV")
    args = parser.parse_args()

    resolve_domains(args.input, args.output)
