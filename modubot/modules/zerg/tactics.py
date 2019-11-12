import random

import sc2
from sc2.constants import *
from sc2.units import Units

from modubot.modules.module import BotModule
from modubot.common import BaseStructures, list_diff, list_flatten, retreat, is_worker

# Note: This does a little more than micro, and parts could work for other races.
# allowing it for now in the name of finishing the refactor.
class ZergMicro(BotModule):
  def __init__(self, bot):
    super().__init__(bot)
    bot.shared.burrow_researched = False

  async def on_upgrade_complete(self, upgrade):
    if upgrade == UpgradeId.BURROW:
      self.shared.burrow_researched = True

  async def on_step(self, iteration):
    await self.arrange()
    await self.queens_transfuse()
    return

  async def arrange(self):
    for effect in self.state.effects:
      if effect.id == EffectId.PSISTORMPERSISTENT:
        for position in effect.positions:
          for unit in self.units.closer_than(4, position):
            self.do(unit.move(unit.position.towards(position, -2)))

    if self.shared.burrow_researched:
      unburrowed_roaches = self.units(UnitTypeId.ROACH)
      burrowed_roaches = self.units(UnitTypeId.ROACHBURROWED)
      if unburrowed_roaches.empty and burrowed_roaches.empty:
        return
      to_burrow = unburrowed_roaches.filter(lambda r: r.health < 40)
      to_unburrow = burrowed_roaches.filter(lambda r: r.health > 120)
      for roach in to_burrow:
        self.do(roach(AbilityId.BURROWDOWN))

      for roach in to_unburrow:
        self.do(roach(AbilityId.BURROWUP))

  async def queens_transfuse(self):
    wounded_units = self.units.filter(lambda u: u.health_percentage < 0.2)
    if wounded_units.empty:
      return

    healable_units = wounded_units.filter(lambda u: self.units.filter(lambda ally: ally.energy >= 50 and ally.type_id == UnitTypeId.QUEEN).closer_than(5, u).exists)
    if healable_units.empty:
      return

    for healable_unit in healable_units:
      queen = self.units.filter(lambda ally: ally.energy >= 50 and ally.type_id == UnitTypeId.QUEEN).closer_than(5, healable_unit)
      if queen.exists:
        selected_queen = queen.first
        if selected_queen.is_idle or selected_queen.orders[0].ability != AbilityId.TRANSFUSION_TRANSFUSION:
          self.do(selected_queen(AbilityId.TRANSFUSION_TRANSFUSION, healable_unit))