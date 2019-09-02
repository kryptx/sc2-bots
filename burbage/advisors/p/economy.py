import random

import sc2
from sc2.constants import *
from sc2.position import Point2

from burbage.advisors.advisor import Advisor
from burbage.common import Urgency, TrainingRequest, StructureRequest, ExpansionRequest, list_diff, list_flatten

WORKER_LIMIT = 66

class ProtossEconomyAdvisor(Advisor):
  def __init__(self, manager):
    super().__init__(manager)

  async def tick(self):
    await self.manager.distribute_workers()
    requests = []
    assimilators = self.manager.structures(UnitTypeId.ASSIMILATOR)
    nexuses = self.manager.townhalls
    nodes = self.get_mineable_nodes()

    self.check_worker_health(nodes, assimilators, requests)
    self.check_vespene_status(nexuses, assimilators, requests)
    self.maybe_expand(nodes, assimilators, requests)

    pylon_urgency = self.determine_pylon_urgency()

    if pylon_urgency:
      nexus = self.find_base()
      pylon_position = None
      if nexus:
        pylon_position = nexus.position.towards_with_random_angle(self.resource_centroid(nexus), random.randint(-14,-3))
      else:
        # Why even bother? but sure. okay
        self.attack_with_workers() # might as well. while we're here
        pylon_position = self.manager.start_location.towards_with_random_angle(self.manager.game_info.map_center, random.randint(4, 12))
      requests.append(StructureRequest(UnitTypeId.PYLON, pylon_position, pylon_urgency))

    return requests

  def resource_centroid(self, townhall):
    return Point2.center([r.position for r in self.manager.expansion_locations[townhall.position]])

  def sum_mineral_contents(self, nodes):
    return sum([field.mineral_contents for field in nodes])

  def get_mineable_nodes(self):
    return list_flatten([
      self.manager.mineral_field.closer_than(15, th) for th in self.manager.townhalls
    ])

  def get_empty_geysers(self, assimilators):
    return [
      vg for vg in
      list_flatten([ self.manager.vespene_geyser.closer_than(15, th) for th in self.manager.townhalls ])
      if assimilators.empty or assimilators.closer_than(1.0, vg).empty
    ]

  def check_worker_health(self, nodes, assimilators, requests):
    numWorkers = self.manager.workers.amount
    if numWorkers < (len(nodes) * 2 + assimilators.amount*3) and numWorkers <= WORKER_LIMIT:
      for nex in self.manager.townhalls.idle:
        requests.append(TrainingRequest(UnitTypeId.PROBE, nex, Urgency.HIGH))

  def check_vespene_status(self, nexuses, assimilators, requests):
    # Build enough assimilators to keep up with demand. more than that if we're rich.
    if assimilators.amount < nexuses.ready.amount * 2:
      vgs = self.get_empty_geysers(assimilators)
      if vgs:
        # Default to Low urgency, increase if we're behind
        urgency = Urgency.LOW

        # TODO: allow urgency to be increased by other advisors
        if nexuses.ready.amount < assimilators.amount or self.manager.minerals > self.manager.vespene * 3:
          urgency = Urgency.HIGH

        requests.append(StructureRequest(UnitTypeId.ASSIMILATOR, vgs[0], urgency, exact=True))

  def maybe_expand(self, nodes, assimilators, requests):
    nexusUrgency = Urgency.NONE
    mineable = self.sum_mineral_contents(nodes)

    if not self.manager.already_pending(UnitTypeId.NEXUS):
      # Expand as we run out of minerals
      if mineable < 5000:
        nexusUrgency += 1

      if self.manager.workers.amount >= (len(nodes) * 2 + assimilators.amount*3):
        nexusUrgency += 3

      if mineable < 1000:
        nexusUrgency += 2

      if len(nodes) < 10:
        nexusUrgency += 2

      if(nexusUrgency):
        requests.append(ExpansionRequest(nexusUrgency))

  def determine_pylon_urgency(self):
    pylon_urgency = Urgency.NONE

    if self.manager.supply_cap < 200 and not self.manager.already_pending(UnitTypeId.PYLON):
      if self.manager.supply_left <= 0:
        pylon_urgency = Urgency.EXTREME
      if self.manager.supply_left < self.manager.desired_supply_buffer:
        pylon_urgency = Urgency.VERYHIGH
      elif self.manager.supply_left < self.manager.desired_supply_buffer * 1.5:
        pylon_urgency = Urgency.LOW

    return pylon_urgency

  def attack_with_workers(self):
    for worker in self.manager.workers:
      self.manager.do(worker.attack(self.manager.enemy_start_locations[0]))
    return

  def find_base(self):
    bases = self.manager.townhalls
    if bases.ready.exists:
      return bases.ready.random
    elif bases.exists:
      return bases.random
    else:
      return None