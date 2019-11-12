import random

import sc2
from sc2.constants import *
from sc2.units import Units

from modubot.modules.module import BotModule
from modubot.common import BaseStructures, list_diff, list_flatten, retreat, is_worker

# Note: This does a little more than micro, and parts could work for other races.
# allowing it for now in the name of finishing the refactor.
class ProtossMicro(BotModule):
  def __init__(self, bot):
    super().__init__(bot)

  async def on_step(self, iteration):
    await self.arrange()
    return

  async def arrange(self):
    stalkers = self.units(UnitTypeId.STALKER)
    if stalkers.empty:
      return
    stalkers_with_low_shields = stalkers.filter(lambda s: s.shield < 20)
    for stalker in stalkers_with_low_shields:
      if any(enemy.position.is_closer_than(5, stalker.position) for enemy in self.enemy_units):
        def distance_to_stalker(unit):
          return unit.position.distance_to(stalker.position)
        nearest_enemy = min(self.enemy_units, key=distance_to_stalker)
        abilities = await self.get_available_abilities(stalker)

        if AbilityId.EFFECT_BLINK_STALKER in abilities:
          self.do(stalker(AbilityId.EFFECT_BLINK_STALKER, stalker.position.towards(nearest_enemy.position, -5)))
        else:
          self.do(stalker.move(stalker.position.towards(nearest_enemy, -3)))

        self.do(stalker.attack(nearest_enemy.position, queue=True))

    for effect in self.state.effects:
      if effect.id == EffectId.PSISTORMPERSISTENT:
        for position in effect.positions:
          for unit in self.units.closer_than(4, position):
            self.do(unit.move(unit.position.towards(position, -2)))
