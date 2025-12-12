# CN Assignment 2 – DNS Experiments

## Quick Start
- `python3 -m venv .venv && source .venv/bin/activate`
- `pip install --upgrade pip`
- `pip install -r requirements.txt`
- `mkdir -p results logs` to prime output folders
- store PCAPs inside `pcaps/` (already ignored by git)

## Repository Layout
- `topology.py` brings up the Mininet topology for Task A and automation
- `src/custom_resolver.py` implements the DNS resolver with logging, caching, recursion
- `src/dns_batch_runner.py` replays query lists and records per-host metrics
- `src/main.py` automates Tasks B/D/E/F directly
- `src/plot_dns_metrics.py` produces the plots required for Task D
- `pcap_queries/` holds the DNS names extracted from the PCAP traces
- `results/` and `logs/` are created on demand and contain experiment artefacts

## Automation Entry Point
- `sudo python3 src/main.py <phase> [flags]` drives the Mininet topology and experiment loops
- supported phases: `system-baseline`, `custom-iterative`, `custom-recursive`
- common flags: `--with-nat`, `--gateway-ip`, `--resolver-ip`, `--timeout`, `--no-cache`
- outputs land under `results/` while resolver logs are written to `logs/`
 - Note: it’s convenient to keep two terminals open — one for the topology/Mininet CLI, and another for automation and plotting.

## Task Guide

### Task A – Topology Bring-Up
- `sudo python topology.py --with-nat` starts the exact layout from the assignment figure
- NAT exposes `10.0.0.254` so the hosts can reach external DNS servers if needed
- `pingall` in the Mininet CLI must succeed; screenshot the topology and the ping output
- stop the network with `exit`; Mininet will tear the topology down automatically

### Task B – Baseline Using System Resolver
- Start the topology without dropping to the CLI: `sudo python topology.py --with-nat --no-cli`
- Important: inside Mininet, 127.0.0.53 is not reachable. Our runner filters loopback resolvers and falls back to public DNS (8.8.8.8/1.1.1.1). Ensure you attached `--with-nat` so queries can egress.
- In another terminal, run `sudo python3 src/main.py system-baseline --with-nat`
- The automation replays every `pcap_queries/h*_queries.csv` list via the host OS resolver
- Outputs: `results/system/<host>_system_results.csv` and matching summaries
- Metrics include total queries, success/failure counts, mean latency, throughput

Extracting queries with tshark (CSV supported by tools):
- From your PCAPs folder, run the following once per file to produce CSVs:
	- `tshark -r PCAP_1_H1.pcap -Y "dns.flags.response == 0" -T fields -e frame.time_relative -e dns.qry.name -e dns.flags.recdesired -e frame.len -E header=y -E separator=, -E quote=d -E occurrence=f > pcap_queries/h1_queries.csv`
	- Repeat similarly for H2/H3/H4. Or use `scripts/extract_queries.sh`.

### Task C – Point Hosts to the Custom Resolver
- Launch the topology with CLI in one terminal (Mininet CLI): `sudo python topology.py --with-nat`
- Start the resolver on the `dns` host without blocking the CLI: `dns python3 src/custom_resolver.py --log logs/dns_iterative.csv &`
	- Tip: verify it’s running with `dns pgrep -af custom_resolver.py`; stop later with `dns pkill -f custom_resolver.py`; optional logs: `dns tail -f logs/dns_iterative.csv`.
- From the Mininet CLI, per client host (h1–h4): back up and update resolver
	- Backup: `h1 cp /etc/resolv.conf /tmp/resolv.conf.bak` (repeat for h2/h3/h4)
	- Point to custom resolver: `h1 sh -c 'echo "nameserver 10.0.0.5" > /etc/resolv.conf'` (repeat for h2/h3/h4)
- Verify with `h1 dig example.com` (and/or h2–h4) that queries leave via the custom resolver
- Capture screenshots of the resolver process, the modified `resolv.conf`, and a successful `dig`

### Task D – Replay Through the Custom Resolver
- Ensure the resolver is running on `dns` (from Task C; cache is enabled by default)
- In another terminal (host shell), run: `sudo python3 src/main.py custom-iterative --with-nat --resolver-ip 10.0.0.5`
- Per-host CSVs and summaries appear under `results/custom_iterative/`
- The resolver log `logs/dns_iterative.csv` contains the required fields plus `request_id`
- Generate Task D plots: `python src/plot_dns_metrics.py --log-file logs/dns_iterative.csv --query-file pcap_queries/h1_queries.txt --limit 10`
	- If you only have CSV query lists, create a TXT list first: `cut -d, -f2 pcap_queries/h1_queries.csv > pcap_queries/h1_queries.txt`

### Task E – Recursive Mode Bonus
- Start the resolver with `--recursive --log logs/dns_recursive.csv`
- Execute `sudo python3 src/main.py custom-recursive --with-nat`
- Optional: create CSV variants that append `,true` per query, or pass `--recursion on` to the runner
- Summaries land in `results/custom_recursive/` while the log captures cache hits and recursion steps

### Task F – Caching Bonus
- Caching is enabled by default; use `--no-cache` to disable when collecting comparative data
- Compare `results/custom_iterative/` (cache enabled) against runs produced with `sudo python3 src/main.py custom-iterative --with-nat --`no-cache``
- The resolver log records `cache_status` per query so cache hit ratio is easy to compute

## Plots and Analysis
- `src/plot_dns_metrics.py` builds two charts: servers visited and latency per query
- Output PNGs go to `results/plots/`; embed them in the report with captions
- The script expects the resolver log plus the original query list to preserve ordering

## Validation and Tips
- The extracted TXT files already list plain domain names (duplicates and `wpad` entries are expected)
- Run `python src/dns_batch_runner.py --help` for advanced knobs (timeouts, recursion, output paths)
- Use `sudo mn -c` to terminate stray processes and remove temporary state from Mininet
- Keep raw logs and summaries for inclusion in the final PDF report and GitHub submission