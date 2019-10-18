from sc2.constants import UnitTypeId

from modubot.common import UnitTypeId, BaseStructures
from modubot.scouting.mission import ScoutingMission, ScoutingMissionStatus, identity

class FindBasesMission(ScoutingMission):
  def __init__(self, bot, unit_priority=[], retreat_while=lambda scout: False, start_when=None):
    if not start_when:
      start_when = lambda: bot.time > 45

    super().__init__(bot, unit_priority, retreat_while, start_when)

  def generate_targets(self):
    self.targets = list(self.enemy_start_locations)

  def evaluate_mission_status(self):
    super().evaluate_mission_status()
    if self.status >= ScoutingMissionStatus.COMPLETE:
      return

    enemy_bases = self.enemy_structures(BaseStructures)
    if enemy_bases.exists:
      print("Find Bases Mission Complete")
      self.status = ScoutingMissionStatus.COMPLETE
