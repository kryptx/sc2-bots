import random

import sc2
from sc2.constants import *
from sc2.units import Units

from burbage.advisors.advisor import Advisor
from burbage.common import BaseStructures, list_diff, list_flatten, retreat

all_effect_ids = [name for name, member in EffectId.__members__.items()]

class ProtossTacticsAdvisor(Advisor):
  def __init__(self, manager):
    super().__init__(manager)
    self.attack_targets = []
    self.last_attack = 0

  async def tick(self):
    await self.arrange()
    return []

  async def arrange(self):
    stalkers = self.manager.units(UnitTypeId.STALKER)
    stalkers_with_low_shields = stalkers.filter(lambda s: s.shield < 20)
    for stalker in stalkers_with_low_shields:
      if any(enemy.position.is_closer_than(6, stalker.position) for enemy in self.manager.enemy_units):
        abilities = await self.manager.get_available_abilities(stalker)
        if AbilityId.EFFECT_BLINK_STALKER in abilities:
          def distance_to_stalker(unit):
            return unit.position.distance_to(stalker.position)
          nearest_enemy = min(self.manager.enemy_units, key=distance_to_stalker)
          self.manager.do(stalker(AbilityId.EFFECT_BLINK_STALKER, stalker.position.towards(nearest_enemy.position, -5)))
          self.manager.do(stalker.attack(nearest_enemy.position, queue=True))

    destructables = self.manager.destructables.filter(lambda d: d.position.is_closer_than(10, self.manager.rally_point))
    if destructables.exists:
      for unit in self.manager.units({ UnitTypeId.ZEALOT, UnitTypeId.STALKER, UnitTypeId.ARCHON }).idle:
        self.manager.do(unit.attack(destructables.first))

    for effect in self.manager.state.effects:
      if effect.id == EffectId.PSISTORMPERSISTENT:
        for position in effect.positions:
          for unit in self.manager.units.closer_than(4, position):
            self.manager.do(unit.move(unit.position.towards(position, -2)))
      if effect.id not in all_effect_ids:
        print(f"UNRECOGNIZED EFFECT ID {effect.id}")

    if not self.manager.rally_point:
      return

    for unit in self.manager.unallocated({ UnitTypeId.ZEALOT, UnitTypeId.STALKER, UnitTypeId.ARCHON }).further_than(15, self.manager.rally_point):
      self.manager.do(retreat(unit, self.manager.rally_point))
