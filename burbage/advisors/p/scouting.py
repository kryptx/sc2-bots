import random

import sc2
from sc2.constants import *
from sc2.units import Units
from sc2.position import Point2

from burbage.advisors.advisor import Advisor
from burbage.common import list_diff, list_flatten

class ScoutingMissionType(enum.IntFlag):
  FIND_BASES = 1,
  EVALUATE_RUSHING = 2,
  EXPLORE = 3,
  REVEAL_MAIN = 4,
  WATCH_ENEMY_ARMY = 5,
  SUPPORT_ATTACK = 6,
  COMPLETE = 10

class Race(enum.IntFlag):
  NONE = 0,
  TERRAN = 1,
  ZERG = 2,
  PROTOSS = 3,
  RANDOM = 4

class ScoutingMission():
  def __init__(self, mission_type, targets=[]):
    self.unit = None
    self.targets = targets
    self.evading = False
    self.evading_since = 0
    self.evade_count = 0
    self.mission = mission_type
    self.last_positions = []
    self.complete = False

class ProtossScoutingAdvisor(Advisor):
  def __init__(self, manager):
    super().__init__(manager)
    self.missions = []
    self.enemy_race = None
    manager.advisor_data.scouting['enemy_army'] = dict()
    manager.advisor_data.scouting['enemy_is_rushing'] = None

  async def on_unit_destroyed(self, unit):
    self.manager.advisor_data.scouting['enemy_army'].pop(unit, None)
    self.manager.tagged_units.scouting.discard(unit)
    for affected_mission in [ m for m in self.missions if m.unit and m.unit.tag == unit ]:
      print("mission unit was destroyed")
      if affected_mission.mission == ScoutingMissionType.EVALUATE_RUSHING:
        affected_mission.complete = True

      affected_mission.unit = None

  async def tick(self):
    if self.enemy_race is None:
      if not self.manager.enemy_race == Race.RANDOM:
        self.enemy_race = self.manager.enemy_race
      elif self.manager.enemy_units.exists:
        self.enemy_race = self.manager.enemy_units.random.race

    self.update_tagged_scouts()    # might not need this depending on how reliable on_unit_destroyed is
    self.update_enemy_unit_data()  # tracking every enemy unit we've seen
    self.evaluate_rush_status()    # interpret data from scouts to determine if they are rushing
    self.evaluate_mission_status() # make sure all the scouts are safe and on track
    self.select_new_scouts()
    return []

  def select_new_scouts(self):
    early_missions = [ ScoutingMissionType.FIND_BASES, ScoutingMissionType.EVALUATE_RUSHING ]
    rush_scout_complete = self.manager.advisor_data.scouting['enemy_is_rushing'] != None
    if self.manager.time > 40 and self.manager.enemy_structures.empty and not rush_scout_complete and not any([m.mission in early_missions for m in self.missions]):
      print("Starting mission to find bases")
      self.missions.append(ScoutingMission(ScoutingMissionType.FIND_BASES))

    elif self.manager.time > 240 and len([ m for m in self.missions if m.mission == ScoutingMissionType.EXPLORE ]) < 1:
      self.missions.append(ScoutingMission(ScoutingMissionType.EXPLORE))

    elif self.manager.time > 360 and len([ m for m in self.missions if m.mission == ScoutingMissionType.EXPLORE ]) < 2:
      self.missions.append(ScoutingMission(ScoutingMissionType.EXPLORE))

  def enemy_army_size(self):
    return len(self.manager.advisor_data.scouting['enemy_army'])

  def enemy_army_dps(self):
    return sum([ u.ground_dps for u in self.manager.advisor_data.scouting['enemy_army'].values() ])

  def update_tagged_scouts(self):
    # remove dead scouts
    self.manager.tagged_units.scouting = { u.tag for u in self.manager.units.tags_in(self.manager.tagged_units.scouting) }

  def update_enemy_unit_data(self):
    for unit in self.manager.enemy_units.filter(lambda u: u.can_attack or u.energy_max > 0):
      self.manager.advisor_data.scouting['enemy_army'][unit.tag] = unit

  def assign_scout(self, mission):
    print("assigning scout to mission")
    claimed_units = list(self.manager.tagged_units.strategy) + list(self.manager.tagged_units.scouting)
    observers = self.manager.units(UnitTypeId.OBSERVER).tags_not_in(claimed_units)
    zealots = self.manager.units(UnitTypeId.ZEALOT).tags_not_in(claimed_units)
    probes = self.manager.units(UnitTypeId.PROBE).tags_not_in(claimed_units)

    if observers.exists:
      mission.unit = observers.closest_to(mission.targets[0])
    elif zealots.exists:
      mission.unit = zealots.closest_to(mission.targets[0])
    elif probes.exists:
      mission.unit = probes.closest_to(mission.targets[0])

    return mission.unit

  def release_scout(self, scout):
    self.manager.tagged_units.scouting.discard(scout.tag)
    if scout.type_id == UnitTypeId.PROBE:
      self.manager.do(scout.gather(self.manager.mineral_field.closer_than(15, self.manager.townhalls.ready.random).random))
    else:
      self.manager.do(scout.move(self.manager.rally_point))

  def evaluate_rush_status(self):
    now = self.manager.time
    enemy_bases = self.manager.enemy_structures({ UnitTypeId.NEXUS, UnitTypeId.COMMANDCENTER, UnitTypeId.HATCHERY, UnitTypeId.LAIR })
    if self.manager.advisor_data.scouting['enemy_is_rushing'] == None:
      known_not_rushing = False
      known_rushing = False
      if now > 240:
        # if we haven't figured it out by now...
        known_not_rushing = True
        # one last chance, though.

      if enemy_bases.amount > 1:
        # they expanded
        print("expansion found")
        known_not_rushing = True
      elif now < 120 and self.enemy_army_dps() > 90:
        # whoa, that's a lot of ... something
        print("Yikes! Menacing army")
        known_rushing = True
      elif enemy_bases.exists and enemy_bases.first.position not in self.manager.enemy_start_locations:
        # looks like an expansion to me
        print("expansion suspected")
        known_not_rushing = True
      else:
        # we haven't found more than one base and if we found one, it's in the start location. Look closer...
        if self.enemy_race == Race.TERRAN:
          rax = self.manager.enemy_structures({ UnitTypeId.BARRACKS })
          # we have to check if the base exists again, because otherwise this will trigger on game start
          if rax.center.distance_to(enemy_bases.first) > 40 or (now > 75 and rax.empty and enemy_bases.exists):
            # hey bro why your rax so far away?
            print("DETECTED TERRAN RUSH")
            known_rushing = True
        if self.enemy_race == Race.ZERG:
          pool = self.manager.enemy_structures({ UnitTypeId.SPAWNINGPOOL })
          if pool.exists and enemy_bases.exists:
            print("DETECTED ZERG RUSH")
            known_rushing = True
        if self.enemy_race == Race.PROTOSS:
          dangers = self.manager.enemy_structures({ UnitTypeId.PYLON, UnitTypeId.GATEWAY })
          gates = self.manager.enemy_structures({ UnitTypeId.GATEWAY })
          if dangers.closest_to(self.manager.start_location).is_closer_than(50, self.manager.start_location) or (now > 75 and gates.empty and enemy_bases.exists):
            print("DETECTED PROTOSS RUSH")
            known_rushing = True

      if known_rushing:
        print("Rush detected.")
        self.manager.advisor_data.scouting['enemy_is_rushing'] = True
      elif known_not_rushing:
        print("No rush coming.")
        self.manager.advisor_data.scouting['enemy_is_rushing'] = False

      if known_rushing or known_not_rushing:
        for mission in self.missions:
          if mission.mission == ScoutingMissionType.EVALUATE_RUSHING:
            mission.complete = True

  def evaluate_mission_status(self):
    now = self.manager.time
    enemy_bases = self.manager.enemy_structures({ UnitTypeId.NEXUS, UnitTypeId.COMMANDCENTER, UnitTypeId.HATCHERY, UnitTypeId.LAIR })
    for mission in self.missions:
      if mission.complete:
        if mission.unit:
          self.release_scout(mission.unit)
        mission.unit = None
        continue

      scout = self.manager.units.tags_in([ mission.unit.tag ]).first if mission.unit else None

      if mission.mission == ScoutingMissionType.FIND_BASES and enemy_bases.exists:
        print("Upgrading FIND_BASES to EVALUATE_RUSHING")
        # done with that one, aren't we
        mission.mission = ScoutingMissionType.EVALUATE_RUSHING
        mission.targets.clear()

      if mission.mission in [ ScoutingMissionType.FIND_BASES, ScoutingMissionType.EXPLORE, ScoutingMissionType.EVALUATE_RUSHING ]:
        # These mission types are "targeted" meaning the scout will travel to positions in a list
        # the others are procedural, responding to the game situation=
        if not mission.targets or (scout and scout.position.is_closer_than(2.0, mission.targets[0])):
          print("Scout selecting next target")
          self.next_target(mission)

      target = mission.targets[0]
      if not target:
        continue

      if not scout:
        scout = self.assign_scout(mission)
        self.manager.tagged_units.scouting.add(scout.tag)

      danger = self.find_danger(scout)

      if danger.exists and (not mission.evading or mission.evading_since > 2):
        target = scout.position.towards_with_random_angle(danger.center, -2)
        mission.evading = True
        mission.evading_since = now
        mission.evade_count += 1
        if mission.evade_count > 10:
          self.next_target(mission)

      if mission.evading and (now - mission.evading_since) >= 2:
        mission.evading = False
        target = mission.targets[0]

      if target:
        self.manager.do(scout.move(target))

    self.missions = [ m for m in self.missions if not m.complete ]

  def generate_targets(self, mission):
    print("generating targets")
    if mission.mission == ScoutingMissionType.FIND_BASES:
      mission.targets = list(self.manager.enemy_start_locations)
    if mission.mission == ScoutingMissionType.EXPLORE:
      mission.targets = list(self.manager.expansion_locations.keys())
    if mission.mission == ScoutingMissionType.EVALUATE_RUSHING:
      # if the situation is anything other than a single base in the main,
      # this *might* be hit once but that scout is going home soon
      base = self.manager.enemy_structures({ UnitTypeId.NEXUS, UnitTypeId.COMMANDCENTER, UnitTypeId.HATCHERY }).first
      def distance_to_enemy(ramp):
        return ramp.top_center.distance_to(base)

      # TODO: figure out ramp better
      likely_main_ramp = min(self.manager.game_info.map_ramps, key=distance_to_enemy)

      def distance_to_ramp(base):
        return base.distance_to(likely_main_ramp.bottom_center)

      possible_naturals = [ position for position in self.manager.expansion_locations.keys() if position.is_further_than(1.0, base.position) ]
      likely_natural = min(possible_naturals, key=distance_to_ramp)

      corners = [ Point2([6, 6]), Point2([6, -6]), Point2([-6, -6]), Point2([-6, 6]) ]
      mission.targets = list_flatten([[ pos + base.position for pos in corners ], [ likely_natural ] ])

    print(str(len(mission.targets)) + " targets after generation")

  def next_target(self, mission):
    if mission.targets:
      mission.targets.pop(0)
      mission.evade_count = 0
    if not mission.targets:
      self.generate_targets(mission)
    if not mission.targets:
      mission.complete = True

  def find_danger(self, scout):
    enemies = self.manager.enemy_units + self.manager.enemy_structures
    enemies_that_could_hit_scout = enemies.filter(lambda e: (e.ground_dps > 5 or e.air_dps > 5) and e.target_in_range(scout, bonus_distance=1))
    detectors_in_sight_range = enemies.filter(lambda e: e.is_detector and e.distance_to(scout) <= e.sight_range + 1)

    if enemies_that_could_hit_scout.amount == 0:
      return enemies_that_could_hit_scout
    elif scout.is_cloaked and detectors_in_sight_range.amount <= 1:
      return detectors_in_sight_range
    else:
      return enemies_that_could_hit_scout
