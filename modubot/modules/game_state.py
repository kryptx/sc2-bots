import sc2
from sc2.constants import UnitTypeId
from sc2 import Race
from sc2.units import Units

from .module import BotModule
from modubot.common import optimism, is_worker

class SurrenderedException(Exception):
  pass

class GameStateTracker(BotModule):
  def __init__(self, bot):
    super().__init__(bot)
    self.surrender_declared = None
    bot.shared.known_enemy_units = dict()
    bot.shared.optimism = 1

  async def on_start(self):
    if self.race == Race.Terran:
      self.shared.new_base = UnitTypeId.COMMANDCENTER
      self.shared.gas_structure = UnitTypeId.REFINERY
      self.shared.worker_types = { UnitTypeId.SCV, UnitTypeId.MULE }
      self.shared.common_worker = UnitTypeId.SCV
      self.shared.supply_type = UnitTypeId.SUPPLYDEPOT
    elif self.race == Race.Zerg:
      self.shared.new_base = UnitTypeId.HATCHERY
      self.shared.gas_structure = UnitTypeId.EXTRACTOR
      self.shared.worker_types = { UnitTypeId.DRONE }
      self.shared.common_worker = UnitTypeId.DRONE
      self.shared.supply_type = UnitTypeId.OVERLORD
    elif self.race == Race.Protoss:
      self.shared.new_base = UnitTypeId.NEXUS
      self.shared.gas_structure = UnitTypeId.ASSIMILATOR
      self.shared.worker_types = { UnitTypeId.PROBE }
      self.shared.common_worker = UnitTypeId.PROBE
      self.shared.supply_type = UnitTypeId.PYLON

  async def on_step(self, iteration):
    if self.surrender_declared and self.time - self.surrender_declared > 5:
      await self._client.leave()
      raise SurrenderedException("Surrendered")

    self.shared.optimism = optimism(
      self.units.ready.filter(lambda u: not is_worker(u) and u.type_id != UnitTypeId.QUEEN),
      (u for u in self.shared.known_enemy_units.values() if not is_worker(u))
    )

    if self.shared.optimism < 0.02 and not self.surrender_declared:
      self.surrender_declared = self.time
      await self.chat_send("(gameheart)(gg)(gameheart)")

    for unit in self.enemy_units:
      self.shared.known_enemy_units[unit.tag] = unit

  async def on_unit_destroyed(self, tag):
    self.shared.known_enemy_units.pop(tag, None)

