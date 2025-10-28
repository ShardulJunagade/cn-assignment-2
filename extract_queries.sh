#!/usr/bin/env bash
set -euo pipefail

# Extract DNS query CSVs from all 4 PCAPs into pcap_queries/*.csv

if ! command -v tshark &> /dev/null; then
  echo "tshark could not be found. Please install Wireshark/tshark and try again."
  exit 1
fi

ROOT_DIR=$(pwd)
PCAP_DIR="${ROOT_DIR}/pcaps"
OUT_DIR="${ROOT_DIR}/pcap_queries"
mkdir -p "${OUT_DIR}"

extract() {
  local in_file=$1
  local out_file=$2
  echo "Extracting from ${in_file} -> ${out_file}"
  tshark -r "${in_file}" -Y 'udp.port == 53 && dns.flags.response == 0' \
    -T fields \
    -e frame.time_relative \
    -e dns.qry.name \
    -e dns.flags.recdesired \
    -e frame.len \
    -E header=y -E separator=, -E quote=d -E occurrence=f > "${out_file}"
}

extract "${PCAP_DIR}/PCAP_1_H1.pcap" "${OUT_DIR}/h1_queries.csv"
extract "${PCAP_DIR}/PCAP_2_H2.pcap" "${OUT_DIR}/h2_queries.csv"
extract "${PCAP_DIR}/PCAP_3_H3.pcap" "${OUT_DIR}/h3_queries.csv"
extract "${PCAP_DIR}/PCAP_4_H4.pcap" "${OUT_DIR}/h4_queries.csv"

echo "Done. Files written to ${OUT_DIR}"