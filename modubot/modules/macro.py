from sc2.constants import UnitTypeId, AbilityId
from sc2.position import Point2
from sc2.units import Units

from modubot.common import list_flatten, BaseStructures, TrainingRequest, StructureRequest, Urgency
from modubot.modules.module import BotModule

class MacroManager(BotModule):
  def __init__(self, bot, worker_limit=75):
    super().__init__(bot)
    bot.shared.next_base_location = None
    self.last_base_check = 0  # this is kinda costly
    self.worker_limit = worker_limit

  async def on_step(self, iteration):
    assimilators = self.structures(UnitTypeId.ASSIMILATOR)
    nexuses = self.townhalls
    nodes = self.get_mineable_nodes()

    requests = self.check_worker_health(nodes, assimilators) \
      + self.check_vespene_status(nexuses, assimilators) \
      + self.maybe_expand(nodes, assimilators)

    return requests

  def resource_centroid(self, townhall):
    nodes = self.mineral_field.closer_than(15, townhall)
    if nodes.exists:
      return Point2.center([ r.position for r in nodes ])
    else:
      return self.game_info.map_center

  def find_next_base(self):
    centroid = self.bases_centroid() if self.townhalls.amount > 1 else self.main_base_ramp.bottom_center
    def distance_to_home(location):
      return centroid.distance_to(location)

    all_possible_expansions = [
      loc
      for loc in list(self.expansion_locations.keys())
      if loc not in self.owned_expansions.keys()
        and not self.enemy_structures.closer_than(8, loc).exists
    ]
    return min(all_possible_expansions, key=distance_to_home) if all_possible_expansions else None

  def sum_mineral_contents(self, nodes):
    return sum([field.mineral_contents for field in nodes])

  def get_mineable_nodes(self):
    return list_flatten([
      self.mineral_field.closer_than(15, th) for th in self.townhalls
    ])

  def get_empty_geysers(self, assimilators):
    return [
      vg for vg in
      list_flatten([ self.vespene_geyser.closer_than(15, th) for th in self.townhalls.ready ])
      if assimilators.empty or assimilators.closer_than(1.0, vg).empty
    ]

  def check_worker_health(self, nodes, assimilators):
    requests = []
    # when a worker goes into an assimilator... the bot thinks it doesn't exist.
    numWorkers = self.workers.amount + assimilators.amount
    if numWorkers < min(len(nodes) * 3 + assimilators.amount * 3, self.worker_limit) and self.townhalls.ready.idle.exists:
      requests.append(TrainingRequest(UnitTypeId.PROBE, Urgency.VERYHIGH))
    return requests

  def check_vespene_status(self, nexuses, assimilators):
    requests = []
    # try returning workers that are gathering from an assimilator in progress
    not_ready_assimilator_tags = [nra.tag for nra in assimilators.not_ready]
    for worker in self.workers.gathering.filter(lambda w: w.is_idle or w.orders[0].target in not_ready_assimilator_tags):
      self.do(worker.gather(self.mineral_field.closest_to(worker)))

    vgs = self.get_empty_geysers(assimilators)
    gates = self.structures({ UnitTypeId.GATEWAY, UnitTypeId.WARPGATE })
    if vgs and (gates.amount > 2 or assimilators.amount < gates.amount):
      urgency = Urgency.HIGH if assimilators.exists else Urgency.VERYHIGH
      requests.append(StructureRequest(UnitTypeId.ASSIMILATOR, self.planner, urgency, force_target=vgs[0]))

    return requests

  def maybe_expand(self, nodes, assimilators):
    requests = []
    # this does not have to happen very often
    if not self.shared.next_base_location or self.time - self.last_base_check > 11:
      self.last_base_check = self.time
      if (
        not self.shared.next_base_location
          or any(base.position.is_closer_than(1, self.shared.next_base_location)
        for base in self.townhalls + self.enemy_structures(BaseStructures))
      ):
        self.shared.next_base_location = self.find_next_base()

    if not self.shared.next_base_location:
      return requests

    destructables = self.destructables.filter(lambda d: d.position.is_closer_than(1.0, self.shared.next_base_location))
    if destructables.exists:
      for unit in self.units({ UnitTypeId.ZEALOT, UnitTypeId.STALKER, UnitTypeId.ARCHON }).idle:
        self.do(unit.attack(destructables.first))
    for unit in self.units.closer_than(5, self.shared.next_base_location):
      # apparently, when a probe warps in a building, they become idle before the building has started warping
      if unit.is_idle and unit.type_id != UnitTypeId.PROBE:
        self.do(unit.move(self.shared.next_base_location.towards(self.game_info.map_center, 10)))
    nexus_urgency = Urgency.NONE
    mineable = self.sum_mineral_contents(nodes)
    gates = self.structures({ UnitTypeId.GATEWAY, UnitTypeId.WARPGATE })

    if not self.already_pending(UnitTypeId.NEXUS):
      # don't count bases at start locations, because we know they have one, whether we've seen it or not
      enemy_bases = self.enemy_structures(BaseStructures).filter(lambda base: base.position not in self.enemy_start_locations)
      # if they're out-expanding us
      nexus_urgency = 1 + enemy_bases.amount - self.townhalls.amount

      total_desired_harvesters = len(nodes) * 2 + assimilators.filter(lambda a: a.vespene_contents > 0).amount * 3

      if self.shared.optimism > 1.1:
        nexus_urgency += 1

      # if the enemy has any bases apart from the main... we got this
      if enemy_bases.amount > 0:
        nexus_urgency += 1

      # if we're running out of things to do
      if self.workers.amount >= total_desired_harvesters - 6:
        nexus_urgency += 1

      # if we're really running out of things to do
      if self.workers.amount >= total_desired_harvesters - 3:
        nexus_urgency += 1

      # if we're down to about one base
      if len(nodes) < 10:
        nexus_urgency += 1

      # if it'd be nice to have more income
      if len(nodes) < gates.amount * 3:
        nexus_urgency += 1

      # if we're running out of minerals
      if mineable < 4000:
        nexus_urgency += 1

      if self.townhalls.amount == 1:
        nexus_urgency += 2

      requests.append(StructureRequest(UnitTypeId.NEXUS, planner=None, urgency=nexus_urgency, force_target=self.shared.next_base_location))

    return requests

  def attack_with_workers(self):
    for worker in self.workers:
      self.do(worker.attack(self.enemy_start_locations[0]))
    return

  def find_base(self):
    bases = self.townhalls
    if bases.ready.exists:
      return bases.ready.random
    elif bases.exists:
      return bases.random
    else:
      return None
