from sc2.constants import UnitTypeId

from modubot.scouting.mission import ScoutingMission

class SupportArmyMission(ScoutingMission):
  def __init__(self, unit_priority=[ UnitTypeId.OBSERVER, UnitTypeId.ADEPT, UnitTypeId.PROBE ]):
    super().__init__(unit_priority)
    self.static_targets = False

  def prerequisite(self, bot):
    return bot.units.exists

  def generate_targets(self, bot):
    # if we're defending
    if bot.shared.defenders.exists and bot.shared.threats.exists:
      self.targets = [ bot.shared.defenders.closest_to(bot.shared.threats.center) ]
      return

    # if we're attacking
    if bot.shared.attackers.exists and bot.shared.victims.exists:
      self.targets = [ bot.shared.attackers.closest_to(bot.shared.victims.center) ]
      return

    self.targets = [ bot.shared.rally_point ]
