import random

import sc2
from sc2.constants import *
from sc2.units import Units

from burbage.advisors.advisor import Advisor
from burbage.common import BaseStructures, list_diff, list_flatten

class ProtossTacticsAdvisor(Advisor):
  def __init__(self, manager):
    super().__init__(manager)
    self.attack_targets = []
    self.last_attack = 0

  async def tick(self):
    self.arrange()
    return []

  def arrange(self):
    if not self.manager.rally_point:
      return

    for unit in self.manager.unallocated({ UnitTypeId.ZEALOT, UnitTypeId.STALKER, UnitTypeId.ARCHON }).idle.further_than(8, self.manager.rally_point):
      self.manager.do(unit.attack(self.manager.rally_point))

    for effect in self.manager.state.effects:
      if effect.id == EffectId.PSISTORMPERSISTENT:
        for position in effect.positions:
          for unit in self.manager.units.closer_than(3, position):
            self.manager.do(unit.move(unit.position.towards(position, -2)))

