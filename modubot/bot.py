import logging
import random
import sc2
import sys
import time

from pythonjsonlogger import jsonlogger

from sc2 import Race
from sc2.constants import UnitTypeId, UpgradeId
from sc2.unit_command import UnitCommand
from sc2.units import Units
from sc2.position import Point2

from modubot.modules.game_state import SurrenderedException
from modubot.planners.protoss import ProtossBasePlanner
from modubot.planners.zerg import ZergBasePlanner
from modubot.common import Urgency, list_flatten, OptionsObject, is_worker, LoggerWithFields

def urgencyValue(req):
  return req.urgency

handler = logging.FileHandler(filename='logs/sc2.log',encoding='utf-8')
handler.setFormatter(jsonlogger.JsonFormatter())
logging.basicConfig(level=logging.INFO,handlers=[handler])

### EL BOT ###
class ModuBot(sc2.BotAI):

  def __init__(self, modules=[], limits=dict()):

    self.shared = OptionsObject()  # just a generic object
    self.shared.optimism = 1       # Because the linter is an asshole
    self.unit_command_uses_self_do = True

    # Various info that's often needed
    self.shared.enemy_race = None

    # we'll deal with this once the game starts
    self.planner = None

    # things a consumer should provide
    self.limits = limits
    self.modules = modules

    # for cross-referencing with other bots that are created at the same time
    self.start_time = str(int(time.time()))

  def deallocate(self, tag_set):
    for module in self.modules:
      module.deallocate(tag_set)

  async def on_start(self):
    bot_id = f"{self.start_time}-{self.player_id}-{self.race}"
    self.log = LoggerWithFields(logging.getLogger(), { "bot_id": bot_id, "start_time": self.start_time })
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
    if upgrade_id == UpgradeId.WARPGATERESEARCH:
      self.shared.warpgate_complete = True
    for module in self.modules:
      await module.on_upgrade_complete(upgrade_id)

  def log_request_header(self, iteration):
    self.log.info({
      "message": "Beginning iteration",
      "iteration": iteration,
      "optimism": self.shared.optimism,
      "minerals": self.minerals,
      "vespene": self.vespene,
      "supply_used": self.supply_used,
      "supply_cap": self.supply_cap,
      "known_enemies": len(self.shared.known_enemy_units),
      "allocated": dict(zip(
        [ type(m).__name__ for m in self.modules ],
        [ len(m.allocated) for m in self.modules ],
      ))
    })

  def log_request_result(self, request, original_request, result_msg):
    self.log.info({
      "message": "Request evaluated",
      "urgency": request.urgency,
      "expense": str(request.expense),
      "result": result_msg,
      "request": {
        "type": type(original_request).__name__,
        "expense": original_request.expense,
      }
    })

  async def on_step(self, iteration):
    self.log = self.log.withFields({ "game_time": self.time })
    requests = []
    for module in self.modules:
      try:
        module_result = await module.on_step(iteration) or []
        requests.extend(module_result)
      except SurrenderedException:
        self.log.info("Exiting due to surrender")
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
        self.log.debug({
          "message": "Replacing request",
          "requested": {
            "request_type": type(request),
            "expense": request.expense
          },
          "replacement": {
            "request_type": type(result),
            "expense": result.expense
          }
        })
        request = result
        result = await request.fulfill(self)

      if request.expense in checked:
        self.log_request_result(request, original_request, "duplicate request")
        continue

      checked.add(request.expense)
      cost = self.calculate_cost(request.expense)
      supply_cost = self.calculate_supply_cost(request.expense) if isinstance(request.expense, UnitTypeId) else 0

      if cost.minerals > 0 and mineral_threshold and request.urgency < mineral_threshold:
        self.log_request_result(request, original_request, f"urgency is below mineral threshold (costs {cost.minerals})")
        continue
      if cost.vespene > 0 and vespene_threshold and request.urgency < vespene_threshold:
        self.log_request_result(request, original_request, f"urgency is below vespene threshold (costs {cost.vespene})")
        continue
      if supply_cost > 0 and supply_threshold and request.urgency < supply_threshold:
        self.log_request_result(request, original_request, f"urgency is below supply threshold (costs {supply_cost})")
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
      if result or isinstance(request.expense, UnitTypeId):
        cost_msg = 'real cost deducted'
        minerals -= max(cost.minerals, 0)
        vespene -= max(cost.vespene, 0)
        supply -= max(supply_cost, 0)

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

    handler.flush()
    handler.close()

  def bases_centroid(self):
    return Point2.center([base.position for base in self.townhalls])

  # Modules that want to claim units are required to:
  # - Implement an `urgency` property
  # - report a set of tags of allocated units
  # - respond to requests to deallocate units
  # In exchange for meeting these requirements, a module may add units freely to its allocated set,
  # provided that another module has not claimed them at a higher urgency.
  def unallocated(self, unit_types=None, urgency=Urgency.NONE):
    units = self.units.ready(unit_types) if unit_types else self.units.ready.filter(lambda u: not is_worker(u))
    return units.tags_not_in(list_flatten([
      list(module.allocated) if module.urgency >= urgency
      else []
      for module in self.modules
    ]))
