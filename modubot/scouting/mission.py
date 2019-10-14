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

class ScoutingMissionStatus(enum.IntFlag):
  PENDING = 0,
  ACTIVE = 1,
  COMPLETE = 2,
  FAILED = 3,

async def identity(obj):
  return obj

class ScoutingMission():
  def __init__(self, bot, unit_priority, retreat_while):
    self.bot = bot
    self.unit = None
    self.retreat_until = None             # internal timer for backing off momentarily
    self.retreat_while = retreat_while    # provided function to additionally restrict retreats
    self.status = ScoutingMissionStatus.PENDING
    self.unit_priority = unit_priority
    self.is_lost = False
    self.static_targets = True            # override to false for dynamic scouting missions
    self.targets = []

  def __getattr__(self, name):
    return getattr(self.bot, name)

  def prerequisite(self):
    return True

  def update_targets(self):
    if not (self.static_targets and self.targets):
      self.generate_targets()

    if self.static_targets and self.unit and self.unit.position.is_closer_than(3.0, self.targets[0]):
      self.next_target()

  def next_target(self):
    if self.targets:
      self.targets.pop(0)
    if not self.targets:
      self.generate_targets()
    if not self.targets:
      self.status = ScoutingMissionStatus.COMPLETE

  def evaluate_mission_status(self):
    if self.status >= ScoutingMissionStatus.COMPLETE:
      return
    if self.status == ScoutingMissionStatus.PENDING and self.prerequisite():
      print("Setting scouting mission to active")
      self.status = ScoutingMissionStatus.ACTIVE

  # functions for override
  async def on_unit_destroyed(self, tag):
    return

  def generate_targets(self):
    return

