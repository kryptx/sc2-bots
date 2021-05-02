# Module-based bot for SC2
## Running the bot
Requires Python 3.7 or greater. You will also need to set up maps as specified by [Burny](https://github.com/BurnySc2/python-sc2#maps)

Clone this repo, then:

    pip install .
    python -O start.py

## Viewing Instrumentation

    cd infrastructure
    docker-compose up -d
    open localhost:5601

Then in Kibana, import the kibana-dashboard.ndjson file from this repository for an example dashboard. Filebeat should wire up automatically to read the log file produced by the bot, and the dashboards will populate in time.
## Features
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
