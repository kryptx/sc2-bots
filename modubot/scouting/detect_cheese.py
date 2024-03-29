import sc2
from sc2 import Race
from sc2.constants import UnitTypeId
from sc2.position import Point2

from modubot.common import BaseStructures, list_flatten
from modubot.scouting.mission import ScoutingMission, ScoutingMissionStatus, identity

# if they build one of these, we would definitely prefer to expand
HIGH_TECH_STRUCTURES = {
  UnitTypeId.LAIR,
  UnitTypeId.SPIRE,
  UnitTypeId.INFESTATIONPIT,
  UnitTypeId.HYDRALISKDEN,
  UnitTypeId.LURKERDEN,
  UnitTypeId.STARPORT,
  UnitTypeId.STARGATE,
  UnitTypeId.TEMPLARARCHIVE,
  UnitTypeId.ROBOTICSFACILITY,
  UnitTypeId.ROBOTICSBAY
}

# we expect to see these, in addition to production
LOW_TECH_STRUCTURES = {
  UnitTypeId.SPAWNINGPOOL,
  UnitTypeId.ROACHWARREN,
  UnitTypeId.CYBERNETICSCORE
}

PRODUCTION_STRUCTURES = {
  UnitTypeId.BARRACKS,
  UnitTypeId.FACTORY,
  UnitTypeId.GATEWAY,
  UnitTypeId.WARPGATE
}

# For the purpose of this module, "cheese" is any aggression that will win against a fast expansion
class DetectCheeseMission(ScoutingMission):
  def __init__(self, bot, unit_priority=[], retreat_while=lambda scout: False, start_when=None):
    if not start_when:
      start_when = lambda: bot.enemy_structures(BaseStructures).exists

    super().__init__(bot, unit_priority, retreat_while, start_when)

  def evaluate_mission_status(self):
    super().evaluate_mission_status()
    if self.shared.enemy_is_rushing == None:
      now = self.time
      enemy_bases = self.enemy_structures(BaseStructures)
      known_not_rushing = False
      known_rushing = False
      if now > 240:
        # if we haven't figured it out by now...
        known_not_rushing = True
        # one last chance, though.

      if enemy_bases.amount > 1 or \
        enemy_bases.exists and enemy_bases.first.position not in self.enemy_start_locations or \
        self.enemy_structures(HIGH_TECH_STRUCTURES).exists:
        # they expanded or are building at least basic tech.
        known_not_rushing = True
      else:
        prod_structs = self.enemy_structures(PRODUCTION_STRUCTURES)
        if prod_structs.amount > 2:
          known_rushing = True
        elif (prod_structs.exists and enemy_bases.exists and prod_structs.center.distance_to(enemy_bases.first) > 40) or (now > 75 and prod_structs.empty and enemy_bases.exists):
          # hey bro why your gateway/rax so far away?
          known_rushing = True

        if self.shared.enemy_race == Race.Zerg:
          pool = self.enemy_structures({ UnitTypeId.SPAWNINGPOOL })
          # no idea if this timing is right
          if now < 60 and pool.exists:
            known_rushing = True

      if known_rushing:
        self.shared.enemy_is_rushing = True
        self.status = ScoutingMissionStatus.COMPLETE
      elif known_not_rushing:
        self.shared.enemy_is_rushing = False
        self.status = ScoutingMissionStatus.COMPLETE

  def generate_targets(self):
    # if the situation is anything other than a single base in the main,
    # this *might* be hit once but that scout is going home soon
    base = self.enemy_structures(BaseStructures).first
    def distance_to_enemy(ramp):
      return ramp.top_center.distance_to(base)

    # TODO: figure out ramp better
    likely_main_ramp = min(self.game_info.map_ramps, key=distance_to_enemy)
    def distance_to_ramp(base):
      return base.distance_to(likely_main_ramp.bottom_center)

    possible_naturals = [ position for position in self.expansion_locations_dict.keys() if position.is_further_than(1.0, base.position) ]
    likely_natural = min(possible_naturals, key=distance_to_ramp)

    corners = [ Point2([8, 8]), Point2([8, -8]), Point2([-8, -8]), Point2([-8, 8]) ]
    self.targets = list_flatten([[ pos + base.position for pos in corners ], [ likely_natural ] ])

  async def on_unit_destroyed(self, tag):
    # don't just keep streaming workers to their base for 5 minutes
    self.status = ScoutingMissionStatus.FAILED
