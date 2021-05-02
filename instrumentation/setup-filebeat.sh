#!/bin/bash

wait=0
while :
do
  if [[ $wait -gt 180 ]]; then
    exit 1
  fi
  wait=$((wait+1))
  if nc -z es01 9200 && nc -z kibana 5601; then
    exit 0
  fi
  sleep 1
done

setup -E setup.kibana.host=kibana:5601 -E output.elasticsearch.hosts=["es01:9200"]
