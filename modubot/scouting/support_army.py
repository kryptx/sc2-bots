from sc2.constants import UnitTypeId

from modubot.scouting.mission import ScoutingMission, identity

class SupportArmyMission(ScoutingMission):
  def __init__(self, bot, unit_priority=[], retreat_while=lambda scout: False):
    super().__init__(bot, unit_priority, retreat_while)
    self.static_targets = False

  def prerequisite(self):
    return self.units.exists

  def generate_targets(self):
    # if we're defending
    if self.shared.defenders.exists and self.shared.threats.exists:
      self.targets = [ self.shared.defenders.closest_to(self.shared.threats.center) ]
      return

    # if we're attacking
    if self.shared.attackers.exists and self.shared.victims.exists:
      self.targets = [ self.shared.attackers.closest_to(self.shared.victims.center) ]
      return

    self.targets = [ self.shared.rally_point ]
