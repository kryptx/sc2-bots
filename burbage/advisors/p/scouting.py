import asyncio
import random

import sc2
from sc2.constants import *
from sc2.units import Units
from sc2.position import Point2

from burbage.advisors.advisor import Advisor
from burbage.common import Urgency, WarpInRequest, TrainingRequest, StructureRequest, BaseStructures, list_diff, list_flatten

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

TECH_STRUCTURES = { UnitTypeId.LAIR, UnitTypeId.ROACHWARREN, UnitTypeId.CYBERNETICSCORE, UnitTypeId.FACTORY, UnitTypeId.STARPORT }

class ScoutingMission():
  def __init__(self, mission_type, targets=[], unit_priority=[ UnitTypeId.OBSERVER, UnitTypeId.ADEPT, UnitTypeId.PROBE ]):
    self.unit = None
    self.targets = targets
    self.retreat_until = 1 # should be truthy
    self.mission = mission_type
    self.last_positions = []
    self.complete = False
    self.unit_priority = unit_priority
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
    self.cancel_shades = dict() # adept tag to timestamp

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

    self.abort_adept_teleports()
    self.update_tagged_scouts()       # might not need this depending on how reliable on_unit_destroyed is
    self.update_enemy_unit_data()     # tracking every enemy unit we've seen
    self.evaluate_rush_status()       # interpret data from scouts to determine if they are rushing
    await self.evaluate_mission_status()    # make sure all the scouts are safe and on track
    self.audit_missions()
    requests = self.audit_structures() + self.build_robotics_units() + await self.build_gateway_units()
    return requests

  def abort_adept_teleports(self):
    to_cancel = [tag for tag in self.cancel_shades.keys() if self.cancel_shades[tag] <= self.manager.time]
    for adept in self.manager.units.tags_in(to_cancel):
      self.manager.do(adept(AbilityId.CANCEL_ADEPTPHASESHIFT))

    for tag in to_cancel:
      self.cancel_shades.pop(tag)

  def audit_structures(self):
    requests = []
    prereqs = [ self.manager.structures(UnitTypeId.CYBERNETICSCORE).ready,
                self.manager.structures(UnitTypeId.PYLON).ready ]
    if any(not req.exists for req in prereqs):
      return requests

    robos = self.manager.structures(UnitTypeId.ROBOTICSFACILITY)
    bays = self.manager.structures(UnitTypeId.ROBOTICSBAY)
    if robos.empty and not self.manager.already_pending(UnitTypeId.ROBOTICSFACILITY):
      urgency = Urgency.MEDIUM
      if self.manager.time > 300:
        urgency = Urgency.HIGH
      requests.append(StructureRequest(UnitTypeId.ROBOTICSFACILITY, self.manager.planner, urgency))

    elif robos.ready.exists and bays.empty and not self.manager.already_pending(UnitTypeId.ROBOTICSBAY):
      requests.append(StructureRequest(UnitTypeId.ROBOTICSBAY, self.manager.planner, Urgency.LOW))

    return requests

  def audit_missions(self):
    early_missions = [ ScoutingMissionType.FIND_BASES, ScoutingMissionType.DETECT_CHEESE ]
    rush_scout_complete = self.manager.advisor_data.scouting['enemy_is_rushing'] != None

    if self.manager.enemy_structures.empty and self.manager.time > 40 and not rush_scout_complete and not any([m.mission in early_missions for m in self.missions]):
      self.missions.append(ScoutingMission(ScoutingMissionType.FIND_BASES))

    if len([ m for m in self.missions if m.mission == ScoutingMissionType.EXPANSION_HUNT ]) < 1 and rush_scout_complete and self.manager.time > 240:
      self.missions.append(ScoutingMission(ScoutingMissionType.EXPANSION_HUNT))

    if len([ m for m in self.missions if m.mission == ScoutingMissionType.WATCH_ENEMY_ARMY and m.unit_priority[0] == UnitTypeId.ADEPT ]) < 1 and rush_scout_complete and self.manager.enemy_structures(BaseStructures).exists:
      self.missions.append(ScoutingMission(ScoutingMissionType.WATCH_ENEMY_ARMY, unit_priority=[ UnitTypeId.ADEPT, UnitTypeId.PROBE ]))

    if len([ m for m in self.missions if m.mission == ScoutingMissionType.WATCH_ENEMY_ARMY and m.unit_priority[0] == UnitTypeId.ADEPTPHASESHIFT ]) < 1 and rush_scout_complete and self.manager.enemy_structures(BaseStructures).exists:
      self.missions.append(ScoutingMission(ScoutingMissionType.WATCH_ENEMY_ARMY, unit_priority=[ UnitTypeId.ADEPTPHASESHIFT ]))

    if len([ m for m in self.missions if m.mission == ScoutingMissionType.WATCH_ENEMY_ARMY and m.unit_priority[0] == UnitTypeId.OBSERVER ]) < 1 and rush_scout_complete and self.manager.enemy_structures(BaseStructures).exists:
      self.missions.append(ScoutingMission(ScoutingMissionType.WATCH_ENEMY_ARMY, unit_priority=[ UnitTypeId.OBSERVER ]))

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

  def get_scout(self, mission):
    if mission.unit:
      scouts = self.manager.units.tags_in([ mission.unit.tag ])
      if scouts.exists:
        mission.unit = scouts.first
      else:
        mission.unit = None

    if mission.unit and mission.unit.type_id == mission.unit_priority[0]:
      self.manager.tagged_units.scouting.add(mission.unit.tag)

    else:
      for unit_type in mission.unit_priority:
        if mission.unit and mission.unit.type_id == unit_type:
          # no unit better than the one we got
          break
        available_units = self.manager.unallocated(unit_type)
        if unit_type == UnitTypeId.PROBE:
          available_units = available_units.filter(lambda probe: probe.is_idle or probe.is_collecting)
        if available_units.exists:
          if mission.unit:
            self.release_scout(mission.unit)

          mission.unit = available_units.closest_to(mission.targets[0])
          self.manager.tagged_units.scouting.add(mission.unit.tag)
          break

    return mission.unit

  def release_scout(self, scout):
    self.manager.tagged_units.scouting.discard(scout.tag)
    if scout.type_id == UnitTypeId.PROBE:
      mineral_field = self.manager.mineral_field.filter(lambda f: any(th.position.is_closer_than(15, f.position) for th in self.manager.townhalls))
      if mineral_field.exists:
        self.manager.do(scout.gather(mineral_field.random))
    else:
      self.manager.do(scout.move(self.manager.rally_point))

  def evaluate_rush_status(self):
    now = self.manager.time
    enemy_bases = self.manager.enemy_structures(BaseStructures)
    if self.manager.advisor_data.scouting['enemy_is_rushing'] == None:
      known_not_rushing = False
      known_rushing = False
      if now > 240:
        # if we haven't figured it out by now...
        known_not_rushing = True
        # one last chance, though.

      if enemy_bases.amount > 1 or \
        enemy_bases.exists and enemy_bases.first.position not in self.manager.enemy_start_locations or \
        self.manager.enemy_structures(TECH_STRUCTURES).exists:
        # they expanded or are building at least basic tech.
        known_not_rushing = True
      elif now < 120 and self.enemy_army_dps() > 90:
        # whoa, that's a lot of ... something
        known_rushing = True
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
          if now > 120 and pool.exists and enemy_bases.amount < 2:
            known_rushing = True
        if self.enemy_race == Race.PROTOSS:
          dangers = self.manager.enemy_structures({ UnitTypeId.PYLON, UnitTypeId.GATEWAY })
          gates = self.manager.enemy_structures({ UnitTypeId.GATEWAY })
          if dangers.closest_to(self.manager.start_location).is_closer_than(50, self.manager.start_location) or \
            (now > 75 and gates.empty and enemy_bases.exists) or \
            gates.amount > 1 and self.manager.enemy_structures(TECH_STRUCTURES).empty:
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

  async def evaluate_mission_status(self):
    now = self.manager.time
    enemy_bases = self.manager.enemy_structures(BaseStructures)
    for mission in self.missions:
      if mission.complete:
        if mission.unit:
          self.release_scout(mission.unit)
        mission.unit = None
        continue

      if mission.mission == ScoutingMissionType.FIND_BASES and enemy_bases.exists:
        # done with that one, aren't we
        mission.mission = ScoutingMissionType.DETECT_CHEESE
        mission.targets.clear()

      if mission.mission == ScoutingMissionType.EXPANSION_HUNT and mission.targets and \
        enemy_bases.exists and enemy_bases.closer_than(1.0, mission.targets[0]).exists:
        self.next_target(mission)

      if not (mission.static_targets and mission.targets):
        self.generate_targets(mission)
      if not mission.targets:
        continue

      scout = self.get_scout(mission)
      if not scout:
        continue

      if mission.static_targets and scout.position.is_closer_than(2.0, mission.targets[0]):
        self.next_target(mission)

      if mission.complete:
        continue

      target = mission.targets[0]
      danger = self.find_danger(scout, bonus_range=3)

      if danger.exists:
        # evade. If there's more than 2, go to the next target
        # if the 1 chases long enough, give up and try the next
        if scout.is_flying:
          target = scout.position.towards(danger.center, -2)
        else:
          target = self.manager.rally_point
        if scout.shield < scout.shield_max:
          if mission.static_targets and mission.retreat_until and now >= mission.retreat_until:
            # they came after the scout while we were waiting for its shield to recharge
            self.next_target(mission)
          # at this point, the timer is only for the purpose of whether to give up on the current target
          mission.retreat_until = now + 2

        if mission.unit.type_id == UnitTypeId.ADEPT:
          abilities = await self.manager.get_available_abilities(mission.unit)
          if AbilityId.ADEPTPHASESHIFT_ADEPTPHASESHIFT in abilities:
            self.manager.do(mission.unit(AbilityId.ADEPTPHASESHIFT_ADEPTPHASESHIFT, mission.unit.position))
            mission.retreat_until = now + 13
            self.cancel_shades[mission.unit.tag] = now + 6
      else:
        if mission.mission == ScoutingMissionType.WATCH_ENEMY_ARMY and mission.retreat_until:
          target = None
          if now >= mission.retreat_until and mission.unit.shield == mission.unit.shield_max:
            mission.retreat_until = None

      if target:
        self.manager.do(scout.move(target))
      elif mission.retreat_until and now >= mission.retreat_until:
        self.manager.do(scout.stop())

    self.missions = [ m for m in self.missions if not m.complete ]

  def generate_targets(self, mission):
    if mission.mission == ScoutingMissionType.FIND_BASES:
      mission.targets = list(self.manager.enemy_start_locations)
    if mission.mission == ScoutingMissionType.EXPLORE:
      mission.targets = list(self.manager.expansion_locations.keys())
    if mission.mission == ScoutingMissionType.EXPANSION_HUNT:
      enemy_bases = [b.position for b in self.manager.enemy_structures(BaseStructures)]
      our_bases = list(self.manager.owned_expansions.keys())
      mission.targets = [ p for p in self.manager.expansion_locations.keys() if p not in enemy_bases + our_bases ]
    if mission.mission == ScoutingMissionType.DETECT_CHEESE:
      # if the situation is anything other than a single base in the main,
      # this *might* be hit once but that scout is going home soon
      base = self.manager.enemy_structures(BaseStructures).first
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
      is_combat_unit = lambda e: (e.type_id not in (UnitTypeId.PROBE, UnitTypeId.DRONE, UnitTypeId.SCV))
      known_enemy_units = Units(self.manager.advisor_data.scouting['enemy_army'].values(), self.manager).filter(is_combat_unit)

      if known_enemy_units.exists:
        if mission.unit:
          scout = mission.unit
          towards_danger = known_enemy_units.center - scout.position
          to_the_side = Point2([ towards_danger.y, -towards_danger.x ]) if int(self.manager.time / 30) % 2 == 0 else Point2([ -towards_danger.y, towards_danger.x ])
          mission.targets = [ (known_enemy_units.center).towards(known_enemy_units.center + to_the_side, 4) ]
        else:
          mission.targets = [ known_enemy_units.center ]
      else:
        mission.targets = [ b.position for b in self.manager.enemy_structures ]

  def next_target(self, mission):
    if mission.targets:
      mission.targets.pop(0)
    if not mission.targets:
      self.generate_targets(mission)
    if not mission.targets:
      mission.complete = True

  def find_danger(self, scout, bonus_range=1):
    if scout.type_id == UnitTypeId.ADEPTPHASESHIFT:
      # I ain't afraid
      return Units([], self.manager)

    enemies = self.manager.enemy_units + self.manager.enemy_structures
    enemies_that_could_hit_scout = enemies.filter(lambda e: (e.ground_dps > 5 or e.air_dps > 5) and e.target_in_range(scout, bonus_distance=bonus_range))
    return enemies_that_could_hit_scout

  def build_robotics_units(self):
    requests = []
    robos = self.manager.structures(UnitTypeId.ROBOTICSFACILITY)
    if robos.empty:
      return requests

    numObservers = self.manager.units(UnitTypeId.OBSERVER).amount

    for robo in robos.ready.idle:
      urgency = Urgency.MEDIUM
      if numObservers < 1:
        urgency = Urgency.MEDIUMHIGH
      if numObservers < 2:
        requests.append(TrainingRequest(UnitTypeId.OBSERVER, robo, urgency))
        numObservers += 1

    return requests

  async def build_gateway_units(self):
    requests = []
    gateways = self.manager.structures(UnitTypeId.GATEWAY)
    warpgates = self.manager.structures(UnitTypeId.WARPGATE)
    if (gateways + warpgates).empty:
      return requests

    numAdepts = self.manager.units(UnitTypeId.ADEPT).amount

    if numAdepts >= 2:
      return requests

    if warpgates.ready.exists:
      desired_unit = UnitTypeId.ADEPT
      warpgate = warpgates.ready.random
      abilities = await self.manager.get_available_abilities(warpgate)
      if AbilityId.TRAINWARP_ADEPT in abilities:
        pos = self.manager.structures(UnitTypeId.PYLON).closest_to(self.manager.rally_point).position.to2.random_on_distance([2, 5])
        placement = await self.manager.find_placement(AbilityId.TRAINWARP_ADEPT, pos, placement_step=1)

        if not placement is None:
          requests.append(WarpInRequest(desired_unit, warpgate, placement, Urgency.HIGH))

    if numAdepts < 2 and gateways.ready.idle.exists and not self.manager.warpgate_complete:
      requests.append(TrainingRequest(UnitTypeId.ADEPT, gateways.ready.idle.first, Urgency.MEDIUM + 1 - numAdepts))

    return requests