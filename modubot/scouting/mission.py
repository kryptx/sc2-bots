import enum

from sc2.constants import UnitTypeId, AbilityId

class ScoutingMissionType(enum.IntFlag):
  FIND_BASES = 1,
  DETECT_CHEESE = 2,
  EXPLORE = 3,
  REVEAL_MAIN = 4,
  WATCH_ENEMY_ARMY = 5,
  SUPPORT_ATTACK = 6,
  EXPANSION_HUNT = 7,
  COMPLETE = 10

class Race(enum.IntFlag):
  NONE = 0,
  TERRAN = 1,
  ZERG = 2,
  PROTOSS = 3,
  RANDOM = 4

class ScoutingMissionStatus(enum.IntFlag):
  PENDING = 0,
  ACTIVE = 1,
  COMPLETE = 2,
  FAILED = 3,

class ScoutingMission():
  def __init__(self, unit_priority):
    self.unit = None
    self.retreat_until = None
    self.status = ScoutingMissionStatus.PENDING
    self.unit_priority = unit_priority
    self.is_lost = False
    self.static_targets = True         # override to false for dynamic scouting missions
    self.targets = []
    self.cancel_shades = dict()

  def prerequisite(self, bot):
    return True

  def update_targets(self, bot):
    if not (self.static_targets and self.targets):
      self.generate_targets(bot)

    if self.static_targets and self.unit and self.unit.position.is_closer_than(3.0, self.targets[0]):
      self.next_target(bot)

  def next_target(self, bot):
    if self.targets:
      self.targets.pop(0)
    if not self.targets:
      self.generate_targets(bot)
    if not self.targets:
      self.status = ScoutingMissionStatus.COMPLETE

  def evaluate_mission_status(self, bot):
    self.abort_adept_teleports(bot)
    if self.status >= ScoutingMissionStatus.COMPLETE:
      return
    if self.status == ScoutingMissionStatus.PENDING and self.prerequisite(bot):
      print("Setting scouting mission to active")
      self.status = ScoutingMissionStatus.ACTIVE

  async def adjust_for_danger(self, target, enemies, bot):
    # evade. If there's more than 2, go to the next target
    # if the 1 chases long enough, give up and try the next
    now = bot.time
    scout = bot.units.tags_in([ self.unit.tag ]).first
    if scout.is_flying:
      target = scout.position.towards(enemies.center, -2)
    else:
      target = bot.shared.rally_point

    if scout.shield < scout.shield_max:
      if self.static_targets and self.retreat_until and now >= self.retreat_until:
        # they came after the scout while we were waiting for its shield to recharge
        self.next_target(bot)
      # at this point, the timer is only for the purpose of whether to give up on the current target
      self.retreat_until = now + 2

    if scout.type_id == UnitTypeId.ADEPT:
      abilities = await bot.get_available_abilities(scout)
      if AbilityId.ADEPTPHASESHIFT_ADEPTPHASESHIFT in abilities:
        bot.do(scout(AbilityId.ADEPTPHASESHIFT_ADEPTPHASESHIFT, scout.position))
        self.retreat_until = now + 13
        # TODO this is the wrong self
        self.cancel_shades[self.unit.tag] = now + 6

    return target

  # sometimes you only want to do something if there's NOT a threat
  def adjust_for_safety(self, target, bot):
    return target

  # functions for override
  async def on_unit_destroyed(self, tag):
    return

  def generate_targets(self, bot):
    return

  def abort_adept_teleports(self, bot):
    if not self.cancel_shades:
      return

    to_cancel = [tag for tag in self.cancel_shades.keys() if self.cancel_shades[tag] <= bot.time]
    for adept in bot.units.tags_in(to_cancel):
      bot.do(adept(AbilityId.CANCEL_ADEPTPHASESHIFT))

    for tag in to_cancel:
      self.cancel_shades.pop(tag)
