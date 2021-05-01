from sc2.constants import UnitTypeId

from modubot.common import BaseStructures
from modubot.scouting.mission import ScoutingMission, identity

class ExpansionHuntMission(ScoutingMission):
  def __init__(self, bot, unit_priority=[], retreat_while=lambda scout: False, start_when=None):
    if not start_when:
      start_when = lambda: self.enemy_structures.exists and self.time >= 120

    super().__init__(bot, unit_priority, retreat_while, start_when)

  def update_targets(self):
    super().update_targets()
    bases = self.structures(BaseStructures) + self.enemy_structures(BaseStructures)
    if self.targets and bases.exists and bases.closer_than(1.0, self.targets[0]).exists:
      self.next_target()

  def generate_targets(self):
    enemy_bases = [b.position for b in self.enemy_structures(BaseStructures)]
    our_bases = list(self.owned_expansions.keys())
    self.targets = [ p for p in self.expansion_locations_dict.keys() if p not in enemy_bases + our_bases ]
