from sc2.constants import UnitTypeId

from modubot.common import UnitTypeId, BaseStructures
from modubot.scouting.mission import ScoutingMission, ScoutingMissionStatus

class FindBasesMission(ScoutingMission):
  def __init__(self, unit_priority=[ UnitTypeId.OBSERVER, UnitTypeId.ADEPT, UnitTypeId.PROBE ]):
    super().__init__(unit_priority)

  def prerequisite(self, bot):
    return bot.time >= 40

  def generate_targets(self, bot):
    self.targets = list(bot.enemy_start_locations)

  def evaluate_mission_status(self, bot):
    super().evaluate_mission_status(bot)
    if self.status >= ScoutingMissionStatus.COMPLETE:
      return

    enemy_bases = bot.enemy_structures(BaseStructures)
    if enemy_bases.exists:
      print("Find Bases Mission Complete")
      self.status = ScoutingMissionStatus.COMPLETE
