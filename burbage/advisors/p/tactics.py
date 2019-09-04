import random

import sc2
from sc2.constants import *
from sc2.units import Units

from burbage.advisors.advisor import Advisor
from burbage.common import list_diff, list_flatten

class ProtossTacticsAdvisor(Advisor):
  def __init__(self, manager):
    super().__init__(manager)
    self.attack_targets = []

  async def tick(self):
    self.attack()
    self.arrange()
    return []

  def find_danger(self, scout):
    return (
        self.manager.enemy_units +
        self.manager.enemy_structures
      ).filter(lambda e: (
        (e.is_detector and scout.is_cloaked and e.distance_to(scout) <= e.sight_range + 1) or
        (scout.can_be_attacked and e.target_in_range(scout, bonus_distance=1))
      ))

  def attack(self):
    for attacker in self.manager.units().tags_in(self.manager.tagged_units.strategy).idle:
      attack_location = self.manager.enemy_start_locations[0]
      if self.manager.enemy_structures.exists:
        attack_location = self.manager.enemy_structures.random.position
      self.manager.do(attacker.attack(attack_location))

  def arrange(self):
    if not self.manager.rally_point:
      return

    available = self.manager.units({
      UnitTypeId.ZEALOT,
      UnitTypeId.STALKER,
      UnitTypeId.ARCHON
    }).tags_not_in(
      list(self.manager.tagged_units.strategy) +
      list(self.manager.tagged_units.scouting)
    )

    if available.idle.exists:
      for unit in available.idle.further_than(6, self.manager.rally_point):
        self.manager.do(unit.move(self.manager.rally_point))

