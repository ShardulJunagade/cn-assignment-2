#!/usr/bin/python3

from mininet.topo import Topo
from mininet.net import Mininet
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel

class ImageTopo(Topo):
    """
    - 4 switches in a line
    - 4 hosts, one per switch
    - 1 DNS server connected to S2
    """
    def build(self):
        # --- Add Hosts ---
        h1 = self.addHost('h1', ip='10.0.0.1/24')
        h2 = self.addHost('h2', ip='10.0.0.2/24')
        h3 = self.addHost('h3', ip='10.0.0.3/24')
        h4 = self.addHost('h4', ip='10.0.0.4/24')
        dns_host = self.addHost('dns', ip='10.0.0.5/24') # Create host with name 'dns'


        # --- Add Switches ---
        s1 = self.addSwitch('s1', failMode='standalone')
        s2 = self.addSwitch('s2', failMode='standalone')
        s3 = self.addSwitch('s3', failMode='standalone')
        s4 = self.addSwitch('s4', failMode='standalone')

        # --- Add Links ---
        # Host to Switch links
        self.addLink(h1, s1, bw=100, delay='2ms')
        self.addLink(h2, s2, bw=100, delay='2ms')
        self.addLink(h3, s3, bw=100, delay='2ms')
        self.addLink(h4, s4, bw=100, delay='2ms')
        self.addLink(dns_host, s2, bw=100, delay='1ms') # Link the 'dns' host

        # Switch to Switch links
        self.addLink(s1, s2, bw=100, delay='5ms')
        self.addLink(s2, s3, bw=100, delay='8ms')
        self.addLink(s3, s4, bw=100, delay='10ms')


if __name__ == '__main__':
    setLogLevel('info')
    
    print("*** Creating network topology...\n")
    topo = ImageTopo()
    
    net = Mininet(topo=topo,
                  link=TCLink,
                  controller=None) 
    
    print("\n*** Starting network...\n")
    net.start()
    print("*** Your topology is running!\n")

    print("*** Testing connectivity by pinging all hosts...")
    net.pingAll()
    print("*** Network is ready\n")

    print('*** Dropping to CLI (type exit to stop)')
    CLI(net)

    print("*** Stopping network...\n")
    net.stop()