# Advisor bot for SC2

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