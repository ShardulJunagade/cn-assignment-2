source ./.venv/bin/activate


# mkdir -p pcap_queries

# echo "Extracting queries from PCAP_1_H1.pcap..."
# tshark -r pcaps/PCAP_1_H1.pcap -Y "dns.qry.type == 1" -T fields -e dns.qry.name > pcap_queries/h1_queries.txt

# echo "Extracting queries from PCAP_2_H2.pcap..."
# tshark -r pcaps/PCAP_2_H2.pcap -Y "dns.qry.type == 1" -T fields -e dns.qry.name > pcap_queries/h2_queries.txt

# echo "Extracting queries from PCAP_3_H3.pcap..."
# tshark -r pcaps/PCAP_3_H3.pcap -Y "dns.qry.type == 1" -T fields -e dns.qry.name > pcap_queries/h3_queries.txt

# echo "Extracting queries from PCAP_4_H4.pcap..."
# tshark -r pcaps/PCAP_4_H4.pcap -Y "dns.qry.type == 1" -T fields -e dns.qry.name > pcap_queries/h4_queries.txt



mkdir -p results
chmod +x run_dns_test.sh


sudo python topology.py
h1 ./run_dns_test.sh pcap_queries/h1_queries.txt > results/h1_queries_system_summary.txt
h2 ./run_dns_test.sh pcap_queries/h2_queries.txt > results/h2_queries_system_summary.txt
h3 ./run_dns_test.sh pcap_queries/h3_queries.txt > results/h3_queries_system_summary.txt
h4 ./run_dns_test.sh pcap_queries/h4_queries.txt > results/h4_queries_system_summary.txt



