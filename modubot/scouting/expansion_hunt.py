from sc2.constants import UnitTypeId

from modubot.common import BaseStructures
from modubot.scouting.mission import ScoutingMission

class ExpansionHuntMission(ScoutingMission):
  def __init__(self, unit_priority=[ UnitTypeId.OBSERVER, UnitTypeId.ADEPT, UnitTypeId.PROBE ]):
    super().__init__(unit_priority)

  def prerequisite(self, bot):
    return bot.enemy_structures.exists and bot.time >= 120

  def update_targets(self, bot):
    super().update_targets(bot)
    bases = bot.structures(BaseStructures) + bot.enemy_structures(BaseStructures)
    if self.targets and bases.exists and bases.closer_than(1.0, self.targets[0]).exists:
      self.next_target(bot)

  def generate_targets(self, bot):
    enemy_bases = [b.position for b in bot.enemy_structures(BaseStructures)]
    our_bases = list(bot.owned_expansions.keys())
    self.targets = [ p for p in bot.expansion_locations.keys() if p not in enemy_bases + our_bases ]
