#!/usr/bin/env python3
"""Produce DNS resolution plots for Assignment 2."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
import pandas as pd


def load_query_sequence(path: Path, limit: int) -> List[str]:
    domains: List[str] = []
    with path.open() as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            domain = stripped.split(",", 1)[0].strip()
            domains.append(domain)
            if len(domains) >= limit:
                break
    return domains


def select_request_ids(df: pd.DataFrame, domains: Sequence[str]) -> List[Tuple[str, str]]:
    if df.empty:
        return []
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.sort_values("timestamp")

    selected: List[Tuple[str, str]] = []
    used_ids: set[str] = set()
    for domain in domains:
        matches = df[(df["domain"] == domain) & (~df["request_id"].isin(used_ids))]
        if matches.empty:
            continue
        req_id = matches.iloc[0]["request_id"]
        used_ids.add(req_id)
        selected.append((domain, req_id))
    return selected


def build_metrics(df: pd.DataFrame, domain_requests: Sequence[Tuple[str, str]]) -> pd.DataFrame:
    rows = []
    for domain, req_id in domain_requests:
        group = df[df["request_id"] == req_id]
        if group.empty:
            continue
        non_cache = group[group["server_contacted"] != "CACHE"]
        servers_visited = len(non_cache["server_contacted"].unique())
        latency = group["total_time_s"].max() or 0.0
        rows.append({
            "domain": domain,
            "servers_visited": servers_visited,
            "latency_ms": latency * 1000.0,
        })
    return pd.DataFrame(rows)


def plot_metrics(df: pd.DataFrame, title: str, output_path: Path) -> None:
    if df.empty:
        raise SystemExit("No matching resolver events found for the requested domains")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    x_labels = df["domain"].tolist()
    indices = range(len(x_labels))

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), constrained_layout=True)
    axes[0].bar(indices, df["servers_visited"], color="#4f6d7a")
    axes[0].set_title("Servers Visited Per Query")
    axes[0].set_ylabel("Servers")
    axes[0].set_xticks(indices)
    axes[0].set_xticklabels(x_labels, rotation=45, ha="right", fontsize=8)

    axes[1].bar(indices, df["latency_ms"], color="#c05c3a")
    axes[1].set_title("Latency Per Query")
    axes[1].set_ylabel("Latency (ms)")
    axes[1].set_xticks(indices)
    axes[1].set_xticklabels(x_labels, rotation=45, ha="right", fontsize=8)

    fig.suptitle(title)
    plt.savefig(output_path, dpi=200)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot resolver metrics for the first N queries")
    parser.add_argument("--log-file", type=Path, required=True, help="CSV log produced by custom_resolver.py")
    parser.add_argument("--query-file", type=Path, required=True, help="Original query list to preserve ordering")
    parser.add_argument("--limit", type=int, default=10, help="Number of queries to analyse (default: 10)")
    parser.add_argument("--title", default="DNS Resolver Metrics", help="Figure title")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/plots/h1_first10_metrics.png"),
        help="Output PNG path",
    )
    args = parser.parse_args()

    df = pd.read_csv(args.log_file)
    domains = load_query_sequence(args.query_file, args.limit)
    selections = select_request_ids(df, domains)
    metrics = build_metrics(df, selections)
    plot_metrics(metrics, args.title, args.output)


if __name__ == "__main__":
    main()
