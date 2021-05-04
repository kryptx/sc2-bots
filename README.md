# Module-based bot for SC2
## Running the bot
Requires Python 3.7 or greater. You will also need to set up maps as specified by [Burny](https://github.com/BurnySc2/python-sc2#maps)

Clone this repo, then:

    pip install .
    python -O start.py

## Bot Features
* Module-based design, allows composing bots more abstractly
  * Only tell the bot what you actually want - it automatically builds the required tech
* Game state tracking
  * Can remember all units that have been seen
* Smart, effective worker balancing
  * Handles reassignment after lost bases
* Urgency weight system
  * Modules return requests, manager object fulfills highest urgency
  * "Tiered" urgency system.
    * After failure, the manager will still attempt other requests of the same urgency. It will not attempt to fulfill requests of lower urgency.
* Upgrades
  * Provide multiple sets of upgrades, prioritized
  * Each set upgraded in parallel
* Powerful Scouting module
  * Scouting missions take the best available kind of unit for the job
  * Requests robotics with bay, and observers with observer upgrade
  * Scouts take evasive maneuvers - observers are particularly slippery
  * Multiple mission types
    * Find enemy base
    * Detect cheese
    * Watch enemy army
    * Expansion hunt
* Base Attack Module
  * Attacks the base most distant from the enemy army
* Base Defense Module
  * Allocates only enough to defend, so attacks can continue
* Base sequence planning
  * Clear debris blocking the structure
  * Remove any units blocking nexus
* Base layout planning
  * Minimizes probability of blocking units or resource nodes (a few maps still have issues)
* Dynamic army rally points

## Viewing Instrumentation
Totally optional. Requires Docker.

Before starting the monitoring tools for the first time, the mappings should be set up to receive floating point values for optimism and game time. This should be doable with some configuration but I haven't yet found the options; so here are the manual steps:

1. Empty the log/sc2.log and instead save a simple json value such as `{"message":"hello"}`.
1. Start the containers:

        cd infrastructure
        docker-compose up -d
        open localhost:5601
    This will start a three-node elasticsearch cluster, kibana, filebeat, and a filebeat setup container to configure a few things like saved objects in kibana, and open your browser to kibana, which you will have to refresh when it's ready. I haven't reproduced this setup so the `filebeat-setup` container might require a couple `up` attempts if something comes up too fast or slow the first time.
1. After the index has been created by filebeat, you can update the mapping as follows, replacing `INDEX_NAME` with your filebeat index name:

        curl -X PUT 'localhost:9200/INDEX_NAME/_mappings' \
        --header 'Content-Type: application/json' \
        --data-raw '{
          "properties": {
            "optimism": {
              "type": "float"
            },
            "log_optimism": {
              "type": "float"
            },
            "game_time": {
              "type": "float"
            }
          }
        }'
    You can get the index name if needed from http://localhost:9200/_cat/indices. It should be the one that begins with `filebeat-`.
1. Replace the original contents of your logs if you had any.
1. (Optional) Import the kibana-dashboard.ndjson file from this repository for an example dashboard. Filebeat should wire up automatically to read the log file produced by the bot, and the dashboards will populate in time.
1. Run the bot with detailed logging:

        LOG_LEVEL=info python -O start.py
After this, any dashboard at http://localhost:5601 should have access to game data.
