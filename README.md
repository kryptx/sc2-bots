# Advisor bot for SC2

## Principles

* Race-agnostic "Manager" process:
  * handles and prioritizes requests from various long-running advisors.
  * Allocates resources, workers, and army to each advisor.
  * Race-agnostic
* Race-specific Advisors:
  * Economy advisor requests new workers and expansions. Watches supply and manages macro abilities such as spawn larva.
  * Defense advisor requests structures and a few units to protect the base.
  * Strategy advisor scouts, finds enemy bases and units, to determine optimal unit composition, attack paths, and timing.
  * Tactical advisor carries out all attack orders and monitors the base for defense.
* Advisors should assume they are the only one running. Give an appropriate urgency and priority and let the manager decide
* all requests should include a cancel_condition method, so manager knows if they become obsolete