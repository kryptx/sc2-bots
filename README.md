# Advisor bot for SC2

## Features

* Smart, effective worker balancing
  * Handles reassignment after lost bases
* Urgency weight system
  * Advisors make requests, manager object fulfills highest urgency
  * "Tiered" urgency system.
    * After failure, the manager will still attempt other requests of the same urgency. It will not attempt to fulfill requests of lower urgency.
* Upgrades
  * Generally, attack and then armor. But will do shield 1 before attack 3.
  * One forge but aggressive use of chrono boost.
* Powerful Scouting advisor
  * Scouting missions take the best available kind of unit for the job
  * Requests robotics with bay, and observers with observer upgrade
  * Scouts take evasive maneuvers - observers are particularly slippery
  * Multiple mission types
    * Find enemy base
    * Detect cheese
    * Watch enemy army
    * Expansion hunt
* Defense Missions
  * One per known enemy
* Base sequence planning
  * Clear debris blocking the structure
  * Remove any units blocking nexus
* Base layout planning
  * Minimizes probability of blocking units or resource nodes
* Army rally points
  * Dynamic; top of a ramp near a base

To do:
* Change defense missions and attacks to control objectives.
  * Offensive control objectives and defensive control objectives are triggered differently but work the same way.
    * Assess needed units.
    * If units not available, reassess with nearby probes.
    * If units not available, abort and retreat.
    * If units available, position favorably.
    * Once engaged, micro wounded units, minimize splash damage, and avoid targeted projectiles.

## Principles

* Race-agnostic "Manager" process:
  * handles and prioritizes requests from various long-running advisors.
  * Allocates resources, workers, and army to each advisor.
  * Race-agnostic
* Race-specific Advisors:
  * Economy advisor requests new workers and expansions. Watches supply.
  * Strategy advisor finds enemy bases and units, and requests structures to build optimal unit composition. Decides when and where to attack.
  * Tactical advisor manages units to protect the base and execute attacks including micro.
* Advisors should assume they are the only one running. Request everything, give an appropriate urgency and let the manager decide