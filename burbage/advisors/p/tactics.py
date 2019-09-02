import random

import sc2
from sc2.constants import *
from sc2.units import Units

from burbage.advisors.advisor import Advisor
from burbage.common import list_diff, list_flatten

class ProtossTacticsAdvisor(Advisor):
  def __init__(self, manager):
    super().__init__(manager)

  async def tick(self):
    self.scout()
    self.attack()
    await self.arrange()
    return []

  def find_danger(self, scout):
    return (self.manager.enemy_units + self.manager.enemy_structures).filter(lambda e: e.target_in_range(scout))

  def scout(self):
    for scout in self.manager.units().tags_in(self.manager.scout_tags):
      target = None
      danger = self.find_danger(scout)
      if danger.exists:
        target = scout.position.towards(danger.center, -3)
      elif scout.is_idle:
        scout_locations = list(self.manager.expansion_locations.keys()) + self.manager.enemy_start_locations
        target = scout_locations[random.randint(0, len(scout_locations) - 1)]

      if target:
        self.manager.do(scout.move(target))

  def attack(self):
    for attacker in self.manager.units().tags_in(self.manager.attacker_tags).idle:
      attack_location = self.manager.enemy_start_locations[0]
      if self.manager.enemy_structures.exists:
        attack_location = self.manager.enemy_structures.random.position
      self.manager.do(attacker.attack(attack_location))

  async def arrange(self):
    if not self.manager.rally_point:
      return

    available = self.manager.units({
      UnitTypeId.ZEALOT,
      UnitTypeId.STALKER,
      UnitTypeId.ARCHON
    }).tags_not_in(list(self.manager.attacker_tags) + list(self.manager.scout_tags))

    if available.idle.exists:
      for unit in available.idle.further_than(6, self.manager.rally_point):
        self.manager.do(unit.move(self.manager.rally_point))

