#!/usr/bin/env python3
import argparse
import shlex
import time
from pathlib import Path
from subprocess import STDOUT

from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.net import Mininet

from topology import ImageTopo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
QUERY_MAP = {
    "h1": PROJECT_ROOT / "pcap_queries" / "h1_queries.csv",
    "h2": PROJECT_ROOT / "pcap_queries" / "h2_queries.csv",
    "h3": PROJECT_ROOT / "pcap_queries" / "h3_queries.csv",
    "h4": PROJECT_ROOT / "pcap_queries" / "h4_queries.csv",
}
CLIENT_HOSTS = ("h1", "h2", "h3", "h4")


def _attach_nat(net, switch_name, gateway_ip):
    nat = net.addNAT(name="nat0", connect=False, inNamespace=False, ip=f"{gateway_ip}/24")
    net.addLink(nat, net.get(switch_name), bw=100, delay="1ms")
    return nat


def _configure_routes(net, gateway_ip):
    for host_name in (*CLIENT_HOSTS, "dns"):
        host = net.get(host_name)
        host.cmd(f"ip route add default via {gateway_ip}")


def _python_command(script, *args):
    """Construct a python3 command line with proper quoting."""
    quoted = " ".join(shlex.quote(str(token)) for token in (script, *args))
    return f"python3 {quoted}"


def run_batch(host, query_file, mode, output_dir, label, recursion, timeout, resolver_ip, resolver_port):
    script = PROJECT_ROOT / "src" / "dns_batch_runner.py"
    args = [str(query_file), "--mode", mode, "--output-dir", str(output_dir), "--label", label, "--recursion", recursion, "--timeout", str(timeout), "--csv-name", f"{label}_{mode}_results.csv", "--summary-name", f"{label}_{mode}_summary.txt"]
    if mode == "custom" and resolver_ip:
        args.extend(["--nameserver", resolver_ip, "--port", str(resolver_port)])
    command = _python_command(script, *args)
    full = f"cd {shlex.quote(str(PROJECT_ROOT))} && {command}"
    output = host.cmd(full)
    if output:
        print(output)


def configure_host_dns(host, resolver_ip):
    """"Point the host's /etc/resolv.conf to the given resolver IP, backing up the original."""
    # h1 sh -c "echo 'nameserver 8.8.8.8' > /etc/resolv.conf"
    backup_path = f"/tmp/resolv.conf.{host.name}.bak"
    host.cmd(f"cp /etc/resolv.conf {backup_path}")
    host.cmd(f"printf 'nameserver {resolver_ip}\n' > /etc/resolv.conf")
    return backup_path


def restore_host_dns(host, backup_path):
    host.cmd(f"test -f {backup_path} && cat {backup_path} > /etc/resolv.conf && rm -f {backup_path}")


def start_resolver(dns_host, resolver_ip, resolver_port, timeout, log_path, recursive, cache_enabled, stdout_log):
    script = PROJECT_ROOT / "src" / "custom_resolver.py"
    args = ["--listen", resolver_ip, "--port", str(resolver_port), "--timeout", str(timeout), "--log", str(log_path)]
    if recursive:
        args.append("--recursive")
    if not cache_enabled:
        args.append("--no-cache")
    resolver_cmd = _python_command(script, *args)
    full_cmd = f"cd {shlex.quote(str(PROJECT_ROOT))} && {resolver_cmd}"
    stdout_log.parent.mkdir(parents=True, exist_ok=True)
    log_handle = stdout_log.open("w")
    proc = dns_host.popen(full_cmd, shell=True, stdout=log_handle, stderr=STDOUT)
    time.sleep(1.5)
    return proc, log_handle


def stop_resolver(proc, log_handle) :
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except Exception:
        proc.kill()
    log_handle.close()


def run_system_baseline(net: Mininet, args):
    output_dir = args.results_root / "system"
    output_dir.mkdir(parents=True, exist_ok=True)
    for host_name in CLIENT_HOSTS:
        host = net.get(host_name)
        query_path = QUERY_MAP[host_name]
        print(f"[system] Running queries for {host_name} from {query_path.name}")
        run_batch(
            host=host,
            query_file=query_path,
            mode="system",
            output_dir=output_dir,
            label=host_name,
            recursion="inherit",
            timeout=args.timeout,
            resolver_ip=None,
            resolver_port=args.resolver_port,
        )


def run_custom_phase(net: Mininet, args, recursive):
    dns_host = net.get("dns")
    caches_enabled = not args.no_cache
    phase_name = "custom_recursive" if recursive else "custom_iterative"
    output_dir = args.results_root / phase_name
    output_dir.mkdir(parents=True, exist_ok=True)
    log_file = args.log_dir / ("dns_recursive.csv" if recursive else "dns_iterative.csv")
    stdout_log = args.log_dir / f"{phase_name}_stdout.log"

    resolver_proc, log_handle = start_resolver(
        dns_host=dns_host,
        resolver_ip=args.resolver_ip,
        resolver_port=args.resolver_port,
        timeout=args.timeout + 1.0,
        log_path=log_file,
        recursive=recursive,
        cache_enabled=caches_enabled,
        stdout_log=stdout_log,
    )

    backups = {}
    try:
        for host_name in CLIENT_HOSTS:
            host = net.get(host_name)
            backups[host_name] = configure_host_dns(host, args.resolver_ip)

        recursion_mode = "on" if recursive else "off"
        for host_name in CLIENT_HOSTS:
            host = net.get(host_name)
            query_path = QUERY_MAP[host_name]
            print(f"[{phase_name}] Running queries for {host_name} ({'recursive' if recursive else 'iterative'})")
            run_batch(
                host=host,
                query_file=query_path,
                mode="custom",
                output_dir=output_dir,
                label=host_name,
                recursion=recursion_mode,
                timeout=args.timeout,
                resolver_ip=args.resolver_ip,
                resolver_port=args.resolver_port,
            )
    finally:
        for host_name, backup_path in backups.items():
            restore_host_dns(net.get(host_name), backup_path)
        stop_resolver(resolver_proc, log_handle)


def parse_args():
    parser = argparse.ArgumentParser(description="Automate DNS experiments for CS331 Assignment 2")
    parser.add_argument("phase", choices=("system-baseline", "custom-iterative", "custom-recursive"), help="Experiment phase to execute")
    parser.add_argument("--with-nat", action="store_true", help="Attach a NAT for external connectivity")
    parser.add_argument("--gateway-ip", default="10.0.0.254", help="Gateway IP presented by NAT (default: 10.0.0.254)")
    parser.add_argument("--resolver-ip", default="10.0.0.5", help="IP address of the custom resolver host")
    parser.add_argument("--resolver-port", type=int, default=53, help="Port used by the custom resolver (default: 53)")
    parser.add_argument("--timeout", type=float, default=2.0, help="Per-query timeout in seconds")
    parser.add_argument("--results-root", type=Path, default=PROJECT_ROOT / "results", help="Directory for experiment outputs")
    parser.add_argument("--log-dir", type=Path, default=PROJECT_ROOT / "logs", help="Directory for resolver logs")
    parser.add_argument("--no-cache", action="store_true", help="Disable resolver cache for custom phases")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setLogLevel("info")

    topo = ImageTopo()
    net = Mininet(
        topo=topo,
        link=TCLink,
        controller=None,
        autoSetMacs=True,
        autoStaticArp=True,
    )

    nat = None
    if args.with_nat:
        nat = _attach_nat(net, "s2", args.gateway_ip)

    print("*** Starting topology for automation")
    net.start()

    if args.with_nat and nat is not None:
        nat.configDefault()
        _configure_routes(net, args.gateway_ip)

    print("*** Validating connectivity (pingAll)")
    net.pingAll()

    try:
        if args.phase == "system-baseline":
            run_system_baseline(net, args)
        elif args.phase == "custom-iterative":
            run_custom_phase(net, args, recursive=False)
        elif args.phase == "custom-recursive":
            run_custom_phase(net, args, recursive=True)
        else:
            raise ValueError(f"Unknown experiment phase: {args.phase}")

    finally:
        print("*** Stopping topology")
        if nat is not None:
            nat.deleteIntfs()
            net.stop()


if __name__ == "__main__":
    main()
