#!/bin/bash
QUERY_FILE=$1
if [ -z "$QUERY_FILE" ]; then
  echo "Usage: $0 <query_file>"
  exit 1
fi

total_queries=0
successful_queries=0
failed_queries=0
total_latency=0

# Record start time
start_time=$(date +%s.%N)

while read -r url; do
  [ -z "$url" ] && continue # Skip empty lines
  total_queries=$((total_queries + 1))
  
  # Use +tries=1 and +time=2 to set 1 retry and a 2-second timeout
  output=$(dig +tries=1 +time=2 "$url")
  
  query_time=$(echo "$output" | grep "Query time:" | awk '{print $4}')
  status=$(echo "$output" | grep "status:" | awk -F', ' '{print $2}' | awk -F': ' '{print $2}')
  
  # Check for success
  if [ "$status" = "NOERROR" ]; then
    successful_queries=$((successful_queries + 1))
    if [ -n "$query_time" ]; then
      total_latency=$((total_latency + query_time))
    fi
  else
    failed_queries=$((failed_queries + 1))
  fi
done < "$QUERY_FILE"

# Record end time and calculate duration
end_time=$(date +%s.%N)
total_time=$(echo "$end_time - $start_time" | bc)

# --- Calculate Metrics ---
avg_latency="0"
if [ $successful_queries -gt 0 ]; then
  avg_latency=$(echo "scale=2; $total_latency / $successful_queries" | bc)
fi

throughput="0"
if (( $(echo "$total_time > 0" | bc -l) )); then
  throughput=$(echo "scale=2; $total_queries / $total_time" | bc)
fi

# --- Print Results ---
echo "--- Results for $QUERY_FILE ---"
echo "Total Queries: $total_queries"
echo "Successful Resolutions: $successful_queries"
echo "Failed Resolutions: $failed_queries"
echo "Average Lookup Latency (ms): $avg_latency"
echo "Average Throughput (queries/sec): $throughput"
