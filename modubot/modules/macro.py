from sc2.constants import UnitTypeId, AbilityId
from sc2.position import Point2
from sc2.units import Units

from modubot.common import list_flatten, BaseStructures, TrainingRequest, StructureRequest, Urgency, is_worker
from modubot.modules.module import BotModule

class MacroManager(BotModule):
  def __init__(self, bot, worker_limit=75, gas_urgency=None):
    super().__init__(bot)
    bot.shared.next_base_location = None
    self.last_base_check = 0  # this is kinda costly
    self.worker_limit = worker_limit
    # self.gates.amount > 2 or gas_structs.amount < gates.amount
    self.gas_urgency = gas_urgency if gas_urgency \
      else lambda geysers: (Urgency.NONE if not geysers
        else Urgency.HIGH if bot.structures(bot.shared.gas_structure).exists
        else Urgency.VERYHIGH)

  async def on_step(self, iteration):
    gas_structs = self.structures(self.shared.gas_structure)
    nexuses = self.townhalls
    nodes = self.get_mineable_nodes()

    requests = self.check_worker_health(nodes, gas_structs) \
      + self.check_vespene_status(nexuses, gas_structs) \
      + self.maybe_expand(nodes, gas_structs)

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

  def get_empty_geysers(self, gas_structs):
    return [
      vg for vg in
      list_flatten([ self.vespene_geyser.closer_than(15, th) for th in self.townhalls.ready ])
      if gas_structs.empty or gas_structs.closer_than(1.0, vg).empty
    ]

  def check_worker_health(self, nodes, gas_structs):
    requests = []
    # when a worker goes into a gas structure... the bot thinks it doesn't exist.
    numWorkers = self.workers.amount + gas_structs.amount
    if numWorkers < min(len(nodes) * 3 + gas_structs.amount * 3, self.worker_limit) and self.townhalls.ready.idle.exists:
      requests.append(TrainingRequest(UnitTypeId.PROBE, Urgency.VERYHIGH))
    return requests

  def check_vespene_status(self, nexuses, gas_structs):
    requests = []
    # try returning workers that are gathering from a gas structure in progress
    not_ready_gas_struct_tags = [nra.tag for nra in gas_structs.not_ready]
    for worker in self.workers.gathering.filter(lambda w: w.is_idle or w.orders[0].target in not_ready_gas_struct_tags):
      self.do(worker.gather(self.mineral_field.closest_to(worker)))

    vgs = self.get_empty_geysers(gas_structs)
    if vgs:
      urgency = self.gas_urgency(vgs)
      requests.append(StructureRequest(self.shared.gas_structure, self.planner, urgency, force_target=vgs[0]))

    return requests

  def maybe_expand(self, nodes, gas_structs):
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
      for unit in self.units.filter(lambda u: not is_worker(u)).idle:
        self.do(unit.attack(destructables.first))
    for unit in self.units.closer_than(5, self.shared.next_base_location):
      # apparently, when a probe warps in a building, they become idle *before* the building has started warping
      if unit.is_idle and unit.type_id != self.shared.common_worker:
        self.do(unit.move(self.shared.next_base_location.towards(self.game_info.map_center, 10)))
    base_urgency = Urgency.NONE
    mineable = self.sum_mineral_contents(nodes)

    if not self.already_pending(self.shared.new_base):
      # don't count bases at start locations, because we know they have one, whether we've seen it or not
      enemy_bases = self.enemy_structures(BaseStructures).filter(lambda base: base.position not in self.enemy_start_locations)
      # if they're out-expanding us
      base_urgency = 1 + enemy_bases.amount - self.townhalls.amount

      total_desired_harvesters = len(nodes) * 2 + gas_structs.filter(lambda a: a.vespene_contents > 0).amount * 3

      if self.shared.optimism > 1.1:
        base_urgency += 1

      # if the enemy has any bases apart from the main... we got this
      if enemy_bases.amount > 0:
        base_urgency += 1

      # if we're running out of things to do
      if self.workers.amount >= total_desired_harvesters - 6:
        base_urgency += 1

      # if we're really running out of things to do
      if self.workers.amount >= total_desired_harvesters - 3:
        base_urgency += 1

      # if we're down to about one base
      if len(nodes) < 10:
        base_urgency += 1

      # if we're running out of minerals
      if mineable < 4000:
        base_urgency += 1

      if self.townhalls.amount == 1:
        base_urgency += 4

      requests.append(StructureRequest(self.shared.new_base, planner=None, urgency=base_urgency, force_target=self.shared.next_base_location))

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
