#!/bin/bash
# Usage: ./system_resolver_test.sh <query_file>

QUERY_FILE=$1
if [ -z "$QUERY_FILE" ]; then
  echo "Usage: $0 <query_file>"
  exit 1
fi

# --- Setup output paths ---
BASENAME=$(basename "$QUERY_FILE" .txt)
OUT_DIR="results"
mkdir -p "$OUT_DIR"
CSV_FILE="$OUT_DIR/${BASENAME}_system_results.csv"

# --- Initialize counters ---
total_queries=0
successful_queries=0
failed_queries=0
total_latency=0

# --- Create CSV header ---
echo "domain,status,query_time_ms" > "$CSV_FILE"

# --- Start timing ---
start_time=$(date +%s.%N)

# --- Main loop ---
while read -r url; do
  [ -z "$url" ] && continue   # skip blank lines
  total_queries=$((total_queries + 1))

  # dig: 1 try, 2s timeout
  output=$(dig +tries=1 +time=2 "$url" 2>/dev/null)

  # parse fields safely
  query_time=$(grep -m1 "Query time:" <<< "$output" | awk '{print $4}')
  status=$(grep -m1 "status:" <<< "$output" | awk '{print $6}' | tr -d ',')

  if [ "$status" = "NOERROR" ]; then
    successful_queries=$((successful_queries + 1))
    (( total_latency += query_time ))
  else
    failed_queries=$((failed_queries + 1))
  fi

  # log every query to CSV (empty time -> 0)
  query_time=${query_time:-0}
  echo "$url,$status,$query_time" >> "$CSV_FILE"

done < "$QUERY_FILE"

# --- Stop timing ---
end_time=$(date +%s.%N)
total_time=$(echo "$end_time - $start_time" | bc)

# --- Metrics ---
avg_latency=0
if [ $successful_queries -gt 0 ]; then
  avg_latency=$(echo "scale=2; $total_latency / $successful_queries" | bc)
fi

throughput=0
if (( $(echo "$total_time > 0" | bc -l) )); then
  throughput=$(echo "scale=2; $total_queries / $total_time" | bc)
fi

# --- Summary printout ---
echo "--- Results for $QUERY_FILE ---"
echo "Total Queries: $total_queries"
echo "Successful Resolutions: $successful_queries"
echo "Failed Resolutions: $failed_queries"
echo "Average Lookup Latency (ms): $avg_latency"
echo "Average Throughput (queries/sec): $throughput"
echo "Per-query results saved to: $CSV_FILE"
