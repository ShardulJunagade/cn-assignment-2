echo "Extracting queries from PCAP_1_H1.pcap..."
tshark -r pcaps/PCAP_1_H1.pcap -Y "dns.qry.type == 1" -T fields -e dns.qry.name > pcap_queries/h1_queries.txt

echo "Extracting queries from PCAP_2_H2.pcap..."
tshark -r pcaps/PCAP_2_H2.pcap -Y "dns.qry.type == 1" -T fields -e dns.qry.name > pcap_queries/h2_queries.txt

echo "Extracting queries from PCAP_3_H3.pcap..."
tshark -r pcaps/PCAP_3_H3.pcap -Y "dns.qry.type == 1" -T fields -e dns.qry.name > pcap_queries/h3_queries.txt

echo "Extracting queries from PCAP_4_H4.pcap..."
tshark -r pcaps/PCAP_4_H4.pcap -Y "dns.qry.type == 1" -T fields -e dns.qry.name > pcap_queries/h4_queries.txt