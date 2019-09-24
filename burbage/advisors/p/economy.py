import random

import sc2
from sc2.constants import *
from sc2.position import Point2
from sc2.units import Units

from burbage.advisors.advisor import Advisor
from burbage.common import Urgency, TrainingRequest, StructureRequest, ExpansionRequest, BaseStructures, list_diff, list_flatten

WORKER_LIMIT = 66

class ProtossEconomyAdvisor(Advisor):
  def __init__(self, manager):
    super().__init__(manager)
    self.last_distribute = 0
    self.next_base_location = None

  def distribute_workers(self):
    # Only do anything once every 3 seconds
    if self.manager.time - self.last_distribute < 3:
      return

    self.last_distribute = self.manager.time

    # Kinda hard to gather anything without a nexus
    if not self.manager.townhalls.ready.exists:
      return

    # assimilators probably at bases that have been destroyed
    bad_assimilators = self.manager.structures(
      UnitTypeId.ASSIMILATOR
    ).filter(
      lambda a: all(ex.is_further_than(15, a) for ex in self.manager.owned_expansions.keys())
    )

    # assimilators that don't have enough harvesters
    needy_assimilators = self.manager.structures(
      UnitTypeId.ASSIMILATOR
    ).ready.tags_not_in([
      a.tag
      for a in bad_assimilators
    ]).filter(
      lambda a: a.assigned_harvesters < 3
    )

    # mineral patches near one of our bases
    acceptable_minerals = self.manager.mineral_field.filter(
      lambda node: any([
        nex.position.is_closer_than(15, node.position)
        for nex in self.manager.townhalls.ready
      ])
    )

    # tag collections for easy selection and matching
    acceptable_mineral_tags = [ f.tag for f in acceptable_minerals ]
    needy_mineral_tags = [
      f.tag
      for f in acceptable_minerals
      if self.manager.townhalls.closest_to(f.position).surplus_harvesters < 0
    ]

    # anywhere else is strictly forbidden
    unacceptable_mineral_tags = [ f.tag for f in self.manager.mineral_field.tags_not_in(acceptable_mineral_tags) ]

    bad_workers = self.manager.workers.filter(lambda p:
      # Grab these suckers first
      p.is_idle or
      (p.is_gathering and p.orders[0].target in unacceptable_mineral_tags) or
      (p.is_gathering and p.orders[0].target in bad_assimilators)
    )

    # up to N workers, where N is the number of surplus harvesters, from each nexus where there are any
    # may not grab them all every time (it gets only the ones returning minerals), but it'll get enough
    excess_workers = Units(list_flatten([
        self.manager.workers.filter(
          lambda probe: probe.is_carrying_minerals and probe.orders and probe.orders[0].target == nex.tag
        )[0:nex.surplus_harvesters] for nex in self.manager.townhalls.filter(lambda nex: nex.surplus_harvesters > 0)
    ]), self.manager)

    # to fill up your first assimilator, you'll need these
    mining_workers = self.manager.workers.filter(lambda p:
      # if more are needed, this is okay too
      p.is_gathering and (p.orders[0].target in acceptable_mineral_tags or p.is_carrying_minerals)
    ) - (bad_workers + excess_workers)

    usable_workers = bad_workers + excess_workers + mining_workers

    taken_workers = 0
    def get_workers(num):
      nonlocal taken_workers
      if taken_workers + num > usable_workers.amount:
        return []
      taken_workers += num
      return usable_workers[ taken_workers - num : taken_workers ]

    for needy_assimilator in needy_assimilators:
      workers = get_workers(3 - needy_assimilator.assigned_harvesters)
      for worker in workers:
        self.manager.do(worker.gather(needy_assimilator))

    if taken_workers < bad_workers.amount and acceptable_mineral_tags:
      remaining_bad_workers = get_workers(bad_workers.amount - taken_workers)
      for worker in remaining_bad_workers:
        self.manager.do(worker.gather(self.manager.mineral_field.tags_in(acceptable_mineral_tags).random))

    if taken_workers < bad_workers.amount + excess_workers.amount and needy_mineral_tags:
      remaining_excess_workers = get_workers(bad_workers.amount + excess_workers.amount - taken_workers)
      for worker in remaining_excess_workers:
        self.manager.do(worker.gather(self.manager.mineral_field.tags_in(needy_mineral_tags).random))

  async def tick(self):
    self.distribute_workers()
    assimilators = self.manager.structures(UnitTypeId.ASSIMILATOR)
    nexuses = self.manager.townhalls
    nodes = self.get_mineable_nodes()

    requests = self.check_worker_health(nodes, assimilators) \
      + self.check_vespene_status(nexuses, assimilators) \
      + self.maybe_expand(nodes, assimilators)

    pylon_urgency = self.determine_pylon_urgency()

    if pylon_urgency:
      requests.append(StructureRequest(UnitTypeId.PYLON, self.manager.planner, pylon_urgency))

    return requests

  def resource_centroid(self, townhall):
    nodes = self.manager.mineral_field.closer_than(15, townhall)
    if nodes.exists:
      return Point2.center([ r.position for r in nodes ])
    else:
      return self.manager.game_info.map_center

  def find_next_base(self):
    centroid = self.manager.bases_centroid() if self.manager.townhalls.amount > 1 else self.manager.main_base_ramp.bottom_center
    def distance_to_home(location):
      return centroid.distance_to(location)

    all_possible_expansions = [
      loc
      for loc in list(self.manager.expansion_locations.keys())
      if loc not in self.manager.owned_expansions.keys()
        and not self.manager.enemy_structures.closer_than(8, loc).exists
    ]
    return min(all_possible_expansions, key=distance_to_home) if all_possible_expansions else None

  def sum_mineral_contents(self, nodes):
    return sum([field.mineral_contents for field in nodes])

  def get_mineable_nodes(self):
    return list_flatten([
      self.manager.mineral_field.closer_than(15, th) for th in self.manager.townhalls
    ])

  def get_empty_geysers(self, assimilators):
    return [
      vg for vg in
      list_flatten([ self.manager.vespene_geyser.closer_than(15, th) for th in self.manager.townhalls.ready ])
      if assimilators.empty or assimilators.closer_than(1.0, vg).empty
    ]

  def check_worker_health(self, nodes, assimilators):
    requests = []
    numWorkers = self.manager.workers.amount
    if numWorkers < (len(nodes) * 2 + assimilators.amount*3) and numWorkers <= WORKER_LIMIT:
      for nex in self.manager.townhalls.ready.idle:
        requests.append(TrainingRequest(UnitTypeId.PROBE, nex, Urgency.VERYHIGH))
    return requests

  def check_vespene_status(self, nexuses, assimilators):
    requests = []
    # try returning workers that are gathering from an assimilator in progress
    not_ready_assimilator_tags = [nra.tag for nra in assimilators.not_ready]
    for worker in self.manager.workers.gathering.filter(lambda w: w.is_idle or w.orders[0].target in not_ready_assimilator_tags):
      self.manager.do(worker.gather(self.manager.mineral_field.closest_to(worker)))

    vgs = self.get_empty_geysers(assimilators)
    if vgs:
      for vg in vgs:
        urgency = Urgency.HIGH if assimilators.exists else Urgency.VERYHIGH
        gates = self.manager.structures({ UnitTypeId.GATEWAY, UnitTypeId.WARPGATE })
        if gates.amount < 2 and assimilators.amount >= gates.amount:
          # keep the number of gateways ahead until there are 2 of each
          urgency = Urgency.NONE

        if urgency and not (self.manager.already_pending(UnitTypeId.ASSIMILATOR) - self.manager.structures(UnitTypeId.ASSIMILATOR).not_ready.amount):
          requests.append(StructureRequest(UnitTypeId.ASSIMILATOR, self.manager.planner, urgency, force_target=vgs[0]))

    return requests

  def maybe_expand(self, nodes, assimilators):
    requests = []
    if not self.next_base_location or any(nex.position == self.next_base_location for nex in self.manager.townhalls):
      self.next_base_location = self.find_next_base()
    if not self.next_base_location:
      return requests
    destructables = self.manager.destructables.filter(lambda d: d.position.is_closer_than(1.0, self.next_base_location))
    if destructables.exists:
      for unit in self.manager.units({ UnitTypeId.ZEALOT, UnitTypeId.STALKER, UnitTypeId.ARCHON }).idle:
        self.manager.do(unit.attack(destructables.first))
    for unit in self.manager.units.closer_than(5, self.next_base_location):
      # apparently, when a probe warps in a building, they become idle before the building has started warping
      if unit.is_idle and unit.type_id != UnitTypeId.PROBE:
        self.manager.do(unit.move(self.next_base_location.towards(self.manager.game_info.map_center, 10)))
    nexus_urgency = Urgency.NONE
    mineable = self.sum_mineral_contents(nodes)

    if not self.manager.already_pending(UnitTypeId.NEXUS):
      # don't count bases at start locations, because we know they have one, whether we've seen it or not
      enemy_bases = self.manager.enemy_structures(BaseStructures).filter(lambda base: base.position not in self.manager.enemy_start_locations)
      # if they're out-expanding us
      nexus_urgency = 1 + enemy_bases.amount - self.manager.townhalls.amount

      total_usable_workers = len(nodes) * 2 + assimilators.filter(lambda a: a.vespene_contents > 0).amount * 3

      # if we're running out of things to do
      if self.manager.workers.amount >= total_usable_workers - 6: # deliberately 4 probes below full saturation
        nexus_urgency += 1

      # if we've run out of things to do
      if self.manager.workers.amount >= total_usable_workers: # deliberately 4 probes below full saturation
        nexus_urgency += 1

      # if we're down to about one base
      if len(nodes) < 10:
        nexus_urgency += 2

      # if we're running out of minerals
      if mineable < 5000:
        nexus_urgency += 1

      # if we're REALLY running out of minerals
      if mineable < 1000:
        nexus_urgency += 1

      requests.append(StructureRequest(UnitTypeId.NEXUS, planner=None, urgency=nexus_urgency, force_target=self.next_base_location))

    return requests

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