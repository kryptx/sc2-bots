import random

import sc2
from sc2.constants import *
from sc2.units import Units
from sc2.position import Point2

from burbage.advisors.advisor import Advisor
from burbage.common import Urgency, TrainingRequest, StructureRequest, list_diff, list_flatten

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

BASE_STRUCTURES = { UnitTypeId.NEXUS, UnitTypeId.COMMANDCENTER, UnitTypeId.HATCHERY, UnitTypeId.LAIR, UnitTypeId.HIVE }
TECH_STRUCTURES = { UnitTypeId.LAIR, UnitTypeId.CYBERNETICSCORE, UnitTypeId.FACTORY }

class ScoutingMission():
  def __init__(self, mission_type, targets=[], unit_type=None):
    self.unit = None
    self.targets = targets
    self.last_retreat = 0
    self.evading_since = 0
    self.mission = mission_type
    self.last_positions = []
    self.complete = False
    self.unit_type = unit_type
    self.static_targets = mission_type in [
      ScoutingMissionType.FIND_BASES,
      ScoutingMissionType.EXPLORE,
      ScoutingMissionType.DETECT_CHEESE,
      ScoutingMissionType.EXPANSION_HUNT
    ]

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
      if affected_mission.mission == ScoutingMissionType.DETECT_CHEESE:
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
    self.audit_missions()
    requests = self.audit_structures()        # we'll demand robotics if other advisors don't
    requests += self.build_robotics_units()    # observers only
    return requests

  def audit_structures(self):
    requests = []
    prereqs = [ self.manager.structures(UnitTypeId.CYBERNETICSCORE).ready,
                self.manager.structures(UnitTypeId.PYLON).ready ]
    if any(not req.exists for req in prereqs):
      return requests

    pylon = self.manager.structures(UnitTypeId.PYLON).ready.random
    robos = self.manager.structures(UnitTypeId.ROBOTICSFACILITY)
    bays = self.manager.structures(UnitTypeId.ROBOTICSBAY)
    if robos.empty and not self.manager.already_pending(UnitTypeId.ROBOTICSFACILITY):
      urgency = Urgency.MEDIUM
      if self.manager.time > 300:
        urgency = Urgency.HIGH
      requests.append(StructureRequest(UnitTypeId.ROBOTICSFACILITY, pylon.position, urgency))

    elif robos.ready.exists and bays.empty and not self.manager.already_pending(UnitTypeId.ROBOTICSBAY):
      requests.append(StructureRequest(UnitTypeId.ROBOTICSBAY, pylon.position, Urgency.LOW))

    return requests

  def audit_missions(self):
    early_missions = [ ScoutingMissionType.FIND_BASES, ScoutingMissionType.DETECT_CHEESE ]
    rush_scout_complete = self.manager.advisor_data.scouting['enemy_is_rushing'] != None
    if self.manager.time > 40 and self.manager.enemy_structures.empty and not rush_scout_complete and not any([m.mission in early_missions for m in self.missions]):
      self.missions.append(ScoutingMission(ScoutingMissionType.FIND_BASES))

    elif self.manager.time > 240 and len([ m for m in self.missions if m.mission == ScoutingMissionType.EXPANSION_HUNT ]) < 1:
      self.missions.append(ScoutingMission(ScoutingMissionType.EXPANSION_HUNT))

    if self.manager.time > 240 and len([ m for m in self.missions if m.mission == ScoutingMissionType.WATCH_ENEMY_ARMY ]) < 1:
      self.missions.append(ScoutingMission(ScoutingMissionType.WATCH_ENEMY_ARMY, unit_type=UnitTypeId.OBSERVER))

  def enemy_army_size(self):
    return len(self.manager.advisor_data.scouting['enemy_army'])

  def enemy_army_dps(self):
    return sum([ max(u.ground_dps, u.air_dps) for u in self.manager.advisor_data.scouting['enemy_army'].values() if u.ground_dps > 5 or u.air_dps > 0 ])

  def enemy_army_max_hp(self):
    return sum([ u.health_max + u.shield_max for u in self.manager.advisor_data.scouting['enemy_army'].values() if u.ground_dps > 5 or u.air_dps > 0 ])

  def update_tagged_scouts(self):
    # remove dead scouts
    self.manager.tagged_units.scouting = { u.tag for u in self.manager.units.tags_in(self.manager.tagged_units.scouting) }

  def update_enemy_unit_data(self):
    for unit in self.manager.enemy_units:
      self.manager.advisor_data.scouting['enemy_army'][unit.tag] = unit

  def assign_scout(self, mission):
    claimed_units = list(self.manager.tagged_units.strategy) + list(self.manager.tagged_units.scouting)

    if mission.unit_type:
      available_units = self.manager.units(mission.unit_type).tags_not_in(claimed_units)
      if available_units.exists:
        mission.unit = available_units.closest_to(mission.targets[0])
    else:
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
    enemy_bases = self.manager.enemy_structures(BASE_STRUCTURES)
    if self.manager.advisor_data.scouting['enemy_is_rushing'] == None:
      known_not_rushing = False
      known_rushing = False
      if now > 240:
        # if we haven't figured it out by now...
        known_not_rushing = True
        # one last chance, though.

      if enemy_bases.amount > 1:
        # they expanded
        known_not_rushing = True
      elif now < 120 and self.enemy_army_dps() > 90:
        # whoa, that's a lot of ... something
        known_rushing = True
      elif enemy_bases.exists and enemy_bases.first.position not in self.manager.enemy_start_locations:
        # looks like an expansion to me
        known_not_rushing = True
      else:
        # we haven't found more than one base and if we found one, it's in the start location. Look closer...
        if self.enemy_race == Race.TERRAN:
          rax = self.manager.enemy_structures({ UnitTypeId.BARRACKS })
          # we have to check if the base exists again, because otherwise this will trigger on game start
          if rax.center.distance_to(enemy_bases.first) > 40 or (now > 75 and rax.empty and enemy_bases.exists):
            # hey bro why your rax so far away?
            known_rushing = True
        if self.enemy_race == Race.ZERG:
          pool = self.manager.enemy_structures({ UnitTypeId.SPAWNINGPOOL })
          if pool.exists and enemy_bases.exists:
            known_rushing = True
        if self.enemy_race == Race.PROTOSS:
          dangers = self.manager.enemy_structures({ UnitTypeId.PYLON, UnitTypeId.GATEWAY })
          gates = self.manager.enemy_structures({ UnitTypeId.GATEWAY })
          if dangers.closest_to(self.manager.start_location).is_closer_than(50, self.manager.start_location) or (now > 75 and gates.empty and enemy_bases.exists):
            known_rushing = True

      if known_rushing:
        print("Rush detected.")
        self.manager.advisor_data.scouting['enemy_is_rushing'] = True
      elif known_not_rushing:
        print("No rush coming.")
        self.manager.advisor_data.scouting['enemy_is_rushing'] = False

      if known_rushing or known_not_rushing:
        for mission in self.missions:
          if mission.mission == ScoutingMissionType.DETECT_CHEESE:
            mission.complete = True

  def evaluate_mission_status(self):
    now = self.manager.time
    enemy_bases = self.manager.enemy_structures(BASE_STRUCTURES)
    for mission in self.missions:
      if mission.complete:
        if mission.unit:
          self.release_scout(mission.unit)
        mission.unit = None
        continue

      scout = self.manager.units.tags_in([ mission.unit.tag ]).first if mission.unit else None

      if mission.mission == ScoutingMissionType.FIND_BASES and enemy_bases.exists:
        # done with that one, aren't we
        mission.mission = ScoutingMissionType.DETECT_CHEESE
        mission.targets.clear()

      if mission.static_targets:
        if not mission.targets or (scout and scout.position.is_closer_than(2.0, mission.targets[0])):
          self.next_target(mission)
      else:
        self.generate_targets(mission)

      if mission.mission == ScoutingMissionType.EXPANSION_HUNT and mission.targets and \
        enemy_bases.exists and enemy_bases.closer_than(1.0, mission.targets[0]).exists:
        self.next_target(mission)

      target = mission.targets[0]
      if not target:
        continue

      if not scout:
        scout = self.assign_scout(mission)

      if not scout:
        continue

      self.manager.tagged_units.scouting.add(scout.tag)
      danger = self.find_danger(scout, bonus_range=3)

      if danger.exists:
        if mission.mission == ScoutingMissionType.WATCH_ENEMY_ARMY:
          if danger.amount > 5:
            target = scout.position.towards(danger.center, -2)
            mission.last_retreat = now

        elif danger.amount > 2 and now - mission.last_retreat >= 5:
          # TRY THE NEXT ONE
          self.next_target(mission)
          mission.last_retreat = now
        else:
          if not mission.evading_since:
            mission.evading_since = now
          elif now - mission.evading_since > 5:
            self.next_target(mission)

        # but no matter where we're going we better try to get away from these clowns
        target = scout.position.towards(danger.center, -2)
      else:
        mission.evading_since = None
        if mission.mission == ScoutingMissionType.WATCH_ENEMY_ARMY and mission.last_retreat:
          target = None
          if now - mission.last_retreat > 10:
            mission.last_retreat = None

      if target:
        self.manager.do(scout.move(target))

    self.missions = [ m for m in self.missions if not m.complete ]

  def generate_targets(self, mission):
    if mission.mission == ScoutingMissionType.FIND_BASES:
      mission.targets = list(self.manager.enemy_start_locations)
    if mission.mission == ScoutingMissionType.EXPLORE:
      mission.targets = list(self.manager.expansion_locations.keys())
    if mission.mission == ScoutingMissionType.EXPANSION_HUNT:
      enemy_bases = [b.position for b in self.manager.enemy_structures(BASE_STRUCTURES)]
      our_bases = list(self.manager.owned_expansions.keys())
      mission.targets = [ p for p in self.manager.expansion_locations.keys() if p not in enemy_bases + our_bases ]
    if mission.mission == ScoutingMissionType.DETECT_CHEESE:
      # if the situation is anything other than a single base in the main,
      # this *might* be hit once but that scout is going home soon
      base = self.manager.enemy_structures(BASE_STRUCTURES).first
      def distance_to_enemy(ramp):
        return ramp.top_center.distance_to(base)

      # TODO: figure out ramp better
      likely_main_ramp = min(self.manager.game_info.map_ramps, key=distance_to_enemy)

      def distance_to_ramp(base):
        return base.distance_to(likely_main_ramp.bottom_center)

      possible_naturals = [ position for position in self.manager.expansion_locations.keys() if position.is_further_than(1.0, base.position) ]
      likely_natural = min(possible_naturals, key=distance_to_ramp)

      corners = [ Point2([7, 7]), Point2([7, -7]), Point2([-7, -7]), Point2([-7, 7]) ]
      mission.targets = list_flatten([[ pos + base.position for pos in corners ], [ likely_natural ] ])

    if mission.mission == ScoutingMissionType.WATCH_ENEMY_ARMY:
      # what combat units do we know about?
      is_combat_unit = lambda e: (e.ground_dps > 5 or e.air_dps > 5 or e.energy_max > 0)
      known_enemy_units = Units(self.manager.advisor_data.scouting['enemy_army'].values(), self.manager).filter(is_combat_unit)

      if known_enemy_units.exists:
        mission.targets = [ known_enemy_units.center ]
      else:
        mission.targets = [ self.manager.rally_point ]

  def next_target(self, mission):
    if mission.targets:
      mission.targets.pop(0)
      mission.evading_since = None
    if not mission.targets:
      self.generate_targets(mission)
    if not mission.targets:
      mission.complete = True

  def find_danger(self, scout, bonus_range=1):
    enemies = self.manager.enemy_units + self.manager.enemy_structures
    enemies_that_could_hit_scout = enemies.filter(lambda e: (e.ground_dps > 5 or e.air_dps > 5) and e.target_in_range(scout, bonus_distance=bonus_range))
    detectors_in_sight_range = enemies.filter(lambda e: e.is_detector and e.distance_to(scout) <= e.sight_range + bonus_range)

    if enemies_that_could_hit_scout.amount == 0:
      return enemies_that_could_hit_scout
    elif scout.is_cloaked and detectors_in_sight_range.amount <= 1:
      return detectors_in_sight_range
    else:
      return enemies_that_could_hit_scout

  def build_robotics_units(self):
    requests = []
    robos = self.manager.structures(UnitTypeId.ROBOTICSFACILITY)
    if robos.empty:
      return requests

    numObservers = self.manager.units(UnitTypeId.OBSERVER).amount

    for robo in robos.idle:
      urgency = Urgency.MEDIUM
      if numObservers < 1:
        urgency = Urgency.MEDIUMHIGH
      if numObservers < 2:
        requests.append(TrainingRequest(UnitTypeId.OBSERVER, robo, urgency))
        numObservers += 1

    return requests