import sc2
from sc2.constants import UnitTypeId
from sc2.units import Units

from .module import BotModule
from modubot.common import optimism

class SurrenderedException(Exception):
  pass

class GameStateTracker(BotModule):
  def __init__(self, bot):
    super().__init__(bot)
    self.surrender_declared = None
    bot.shared.known_enemy_units = dict()
    bot.shared.optimism = 1

  async def on_step(self, iteration):
    if self.surrender_declared and self.time - self.surrender_declared > 5:
      await self._client.leave()
      raise SurrenderedException("Surrendered")

    self.shared.optimism = optimism(
      self.units.ready.filter(lambda u: u.type_id not in [ UnitTypeId.PROBE, UnitTypeId.DRONE, UnitTypeId.SCV ]), (
      u for u in self.shared.known_enemy_units.values()
      if u.type_id not in [ UnitTypeId.PROBE, UnitTypeId.DRONE, UnitTypeId.SCV ]
    ))

    if self.shared.optimism < 0.01 and not self.surrender_declared:
      self.surrender_declared = self.time
      await self.chat_send("(gameheart)(gg)(gameheart)")

    for unit in self.enemy_units:
      self.shared.known_enemy_units[unit.tag] = unit

  async def on_unit_destroyed(self, tag):
    self.shared.known_enemy_units.pop(tag, None)

