import argparse
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel
from mininet.net import Mininet
from mininet.node import Node
from mininet.topo import Topo
from mininet.clean import cleanup


class ImageTopo(Topo):
    """Four hosts and a DNS server connected in a line of switches."""

    def build(self) -> None:
        # --- Add hosts ---
        h1 = self.addHost("h1", ip="10.0.0.1/24")
        h2 = self.addHost("h2", ip="10.0.0.2/24")
        h3 = self.addHost("h3", ip="10.0.0.3/24")
        h4 = self.addHost("h4", ip="10.0.0.4/24")
        dns_host = self.addHost("dns", ip="10.0.0.5/24")  # Create host with name 'dns'

        # --- Add switches ---
        s1 = self.addSwitch("s1", failMode="standalone")
        s2 = self.addSwitch("s2", failMode="standalone")
        s3 = self.addSwitch("s3", failMode="standalone")
        s4 = self.addSwitch("s4", failMode="standalone")

        # --- Host to switch links ---
        self.addLink(h1, s1, bw=100, delay="2ms")
        self.addLink(h2, s2, bw=100, delay="2ms")
        self.addLink(h3, s3, bw=100, delay="2ms")
        self.addLink(h4, s4, bw=100, delay="2ms")
        self.addLink(dns_host, s2, bw=100, delay="1ms")

        # --- Switch cascade ---
        self.addLink(s1, s2, bw=100, delay="5ms")
        self.addLink(s2, s3, bw=100, delay="8ms")
        self.addLink(s3, s4, bw=100, delay="10ms")


def _attach_nat(net: Mininet, switch_name: str, gateway_ip: str) -> Node:
    """Attach a NAT node to the topology for Internet reachability."""

    nat = net.addNAT(name="nat0", connect=False, inNamespace=False, ip=f"{gateway_ip}/24")
    net.addLink(nat, net.get(switch_name), bw=100, delay="1ms")
    return nat


def _configure_default_routes(net: Mininet, gateway_ip: str) -> None:
    """Point all hosts towards the NAT so external queries can exit."""

    for host_name in ("h1", "h2", "h3", "h4", "dns"):
        host = net.get(host_name)
        host.cmd(f"ip route add default via {gateway_ip}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the CS331 Assignment 2 topology")
    parser.add_argument("--with-nat", action="store_true", help="attach a NAT to reach the Internet")
    parser.add_argument("--nat-switch", default="s2", help="switch that connects to the NAT (default: s2)")
    parser.add_argument("--gateway-ip", default="10.0.0.254", help="gateway IP exposed by the NAT")
    args = parser.parse_args()
    args.with_nat = True  # Always enable NAT for this version

    setLogLevel("info")
    cleanup()

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
        nat = _attach_nat(net, args.nat_switch, args.gateway_ip)

    print("\n*** Starting network...\n")
    net.start()
    print("*** Topology is running.\n")

    if nat is not None:
        nat.configDefault()
        _configure_default_routes(net, args.gateway_ip)
        print("*** NAT configured for external connectivity.\n")

    print("*** Testing connectivity via pingAll()...")
    net.pingAll()
    print("*** Connectivity check complete.\n")

    print("*** Dropping to the Mininet CLI (type 'exit' to stop)")
    CLI(net)

    print("*** Stopping network...\n")
    if nat is not None:
        # Keep the namespace tidy.
        nat.deleteIntfs()
    net.stop()


if __name__ == "__main__":
    main()