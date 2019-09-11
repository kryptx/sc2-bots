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
    self.last_attack = 0

  async def tick(self):
    self.attack()
    self.arrange()
    return []

  def attack(self):
    now = self.manager.time
    if now - self.last_attack < 2:
      return
    self.last_attack = now
    for attacker in self.manager.units().tags_in(self.manager.tagged_units.strategy).idle:
      attack_location = self.manager.enemy_start_locations[0]
      if self.manager.enemy_structures.exists:
        attack_location = self.manager.enemy_structures({
          UnitTypeId.NEXUS,
          UnitTypeId.COMMANDCENTER,
          UnitTypeId.HATCHERY,
          UnitTypeId.LAIR,
          UnitTypeId.HIVE
        }).random.position
      self.manager.do(attacker.attack(attack_location))
    for mission in self.manager.strategy_advisor.defense.values():
      for defender in mission.defenders:
        unit = self.manager.enemy_units.tags_in([ mission.target.tag ])
        if unit.exists:
          self.manager.do(defender.attack(unit.first.position))
        else:
          self.manager.do(defender.attack(mission.target.position))

  def arrange(self):
    if not self.manager.rally_point:
      return

    available = self.manager.units({
      UnitTypeId.ZEALOT,
      UnitTypeId.STALKER,
      UnitTypeId.ARCHON
    }).tags_not_in(
      list(self.manager.tagged_units.strategy) +
      list(self.manager.tagged_units.scouting) +
      [d.tag for d in self.manager.strategy_advisor.defenders]
    )

    if available.idle.exists:
      for unit in available.idle.further_than(6, self.manager.rally_point):
        self.manager.do(unit.attack(self.manager.rally_point))

