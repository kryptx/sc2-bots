import logging
import sc2

from sc2 import Race
from sc2.constants import UnitTypeId
from sc2.unit_command import UnitCommand
from sc2.units import Units
from sc2.position import Point2

from modubot.modules.game_state import SurrenderedException
from modubot.planners.protoss import ProtossBasePlanner
from modubot.planners.zerg import ZergBasePlanner
from modubot.common import Urgency, list_flatten, OptionsObject, is_worker

def urgencyValue(req):
  return req.urgency

### EL BOT ###
class ModuBot(sc2.BotAI):

  def __init__(self, modules=[], limits=dict(), log_level=logging.INFO):
    self.log = logging.getLogger('ModuBot')
    self.log.setLevel(log_level)
    self.shared = OptionsObject()  # just a generic object
    self.shared.optimism = 1       # Because the linter is an asshole

    # Various info that's often needed
    self.shared.enemy_race = None

    # we'll deal with this once the game starts
    self.planner = None

    # things a consumer should provide
    self.limits = limits
    self.modules = modules

  def deallocate(self, tag_set):
    for module in self.modules:
      module.allocated.difference_update(tag_set)

  async def on_start(self):
    if self.race == Race.Protoss:
      self.planner = ProtossBasePlanner(self)
    elif self.race == Race.Zerg:
      self.planner = ZergBasePlanner(self)

    for module in self.modules:
      await module.on_start()

  async def on_end(self, game_result):
    for module in self.modules:
      await module.on_end(game_result)

  async def on_unit_created(self, unit):
    for module in self.modules:
      await module.on_unit_created(unit)

  async def on_unit_destroyed(self, tag):
    for module in self.modules:
      await module.on_unit_destroyed(tag)

  async def on_building_construction_started(self, unit):
    for module in self.modules:
      await module.on_building_construction_started(unit)

  async def on_building_construction_complete(self, unit):
    for module in self.modules:
      await module.on_building_construction_complete(unit)

  async def on_upgrade_complete(self, upgrade_id):
    for module in self.modules:
      await module.on_upgrade_complete(upgrade_id)

  def log_request_header(self, iteration):
    self.log.info(f"--- Iter {iteration} | Opt {self.shared.optimism} | M {self.minerals} | V {self.vespene} | S {self.supply_used}/{self.supply_cap}")

  def log_request_result(self, request, original_request, result_msg):
    request_description = str(request.expense)
    if original_request.expense != request.expense:
      request_description += f" (from {type(original_request).__name__} for {original_request.expense})"
    self.log.info(f"{request.urgency} request for {request_description}: {result_msg}")

  async def on_step(self, iteration):
    requests = []
    for module in self.modules:
      try:
        module_result = await module.on_step(iteration) or []
        requests.extend(module_result)
      except SurrenderedException:
        print("Exiting due to surrender")
        return

    requests.sort(key=urgencyValue, reverse=True)
    mineral_threshold = None
    vespene_threshold = None
    supply_threshold = None
    minerals = self.minerals
    vespene = self.vespene
    supply = self.supply_left
    checked = set()
    self.log_request_header(iteration)
    while requests:
      request = requests.pop(0)
      original_request = request
      if not request.urgency:
        break

      result = await request.fulfill(self)

      while hasattr(result, 'fulfill'):
        self.log.info(f"Replacing {type(request)} for {request.expense} with {type(result)} for {result.expense}")
        request = result
        result = await request.fulfill(self)

      if request.expense in checked:
        self.log_request_result(request, original_request, "duplicate request")
        continue

      checked.add(request.expense)
      cost = self.calculate_cost(request.expense)
      supply_cost = self.calculate_supply_cost(request.expense) if isinstance(request.expense, UnitTypeId) else 0

      thresholds = ( mineral_threshold, vespene_threshold, supply_threshold )
      lowest_threshold = min(thresholds) if all(t != None for t in thresholds) else Urgency.NONE
      if request.urgency < lowest_threshold:
        self.log_request_result(request, original_request, "urgency is below all thresholds")
        break
      if cost.minerals and mineral_threshold and request.urgency < mineral_threshold:
        self.log_request_result(request, original_request, "urgency is below mineral threshold")
        continue
      if cost.vespene and vespene_threshold and request.urgency < vespene_threshold:
        self.log_request_result(request, original_request, "urgency is below vespene threshold")
        continue
      if supply_cost and supply_threshold and request.urgency < supply_threshold:
        self.log_request_result(request, original_request, "urgency is below supply threshold")
        continue

      can_afford = True
      if cost.minerals > 0 and cost.minerals > minerals:
        can_afford = False
        mineral_threshold = request.urgency

      if cost.vespene > 0 and cost.vespene > vespene:
        can_afford = False
        vespene_threshold = request.urgency

      if supply_cost > 0 and supply_cost > supply:
        can_afford = False
        supply_threshold = request.urgency

      cost_msg = 'cost not deducted'
      if result or request.reserve_cost:
        cost_msg = 'cost deducted'
        minerals -= cost.minerals
        vespene -= cost.vespene
        supply -= supply_cost

      if can_afford:
        if not result:
          self.log_request_result(request, original_request,
            f"dependency already in progress ({cost_msg})"
          )
          continue

        self.do(result)
        self.log_request_result(request, original_request, "️✔ Filled")
      else:
        self.log_request_result(request, original_request, f"️Can't afford ({cost_msg})")

  def bases_centroid(self):
    return Point2.center([base.position for base in self.townhalls])

  def unallocated(self, unit_types=None, urgency=Urgency.NONE):
    units = self.units(unit_types) if unit_types else self.units.filter(lambda u: not is_worker(u))
    return units.tags_not_in(list_flatten([
      list(module.allocated) if module.urgency >= urgency
      else []
      for module in self.modules
    ]))
