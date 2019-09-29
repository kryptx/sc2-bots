import asyncio
import random

import sc2
from sc2.constants import *
from sc2.units import Units
from sc2.position import Point2

from burbage.advisors.advisor import Advisor
from burbage.common import Urgency, WarpInRequest, TrainingRequest, StructureRequest, BaseStructures, list_diff, list_flatten, ObjectiveStatus
from burbage.advisors.p.vp_strategy import DefenseObjective, AttackObjective

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

TECH_STRUCTURES = { UnitTypeId.LAIR, UnitTypeId.ROACHWARREN, UnitTypeId.CYBERNETICSCORE, UnitTypeId.FACTORY, UnitTypeId.STARPORT }


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
      target = bot.rally_point

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
  def on_unit_destroyed(self, tag):
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


class DetectCheeseMission(ScoutingMission):
  def __init__(self, unit_priority=[ UnitTypeId.PROBE ]):
    super().__init__(unit_priority)

  def prerequisite(self, bot):
    if bot.enemy_structures(BaseStructures).exists:
      print("Starting Detect Cheese Mission")
      return True
    return False

  def evaluate_mission_status(self, bot):
    super().evaluate_mission_status(bot)
    if bot.advisor_data.scouting['enemy_is_rushing'] == None:
      now = bot.time
      enemy_bases = bot.enemy_structures(BaseStructures)
      known_not_rushing = False
      known_rushing = False
      if now > 240:
        # if we haven't figured it out by now...
        known_not_rushing = True
        # one last chance, though.

      if enemy_bases.amount > 1 or \
        enemy_bases.exists and enemy_bases.first.position not in bot.enemy_start_locations or \
        bot.enemy_structures(TECH_STRUCTURES).exists:
        # they expanded or are building at least basic tech.
        known_not_rushing = True
      elif now < 120 and bot.enemy_army_dps() > 90:
        # whoa, that's a lot of ... something
        known_rushing = True
      else:
        # we haven't found more than one base and if we found one, it's in the start location. Look closer...
        if bot.enemy_race == Race.TERRAN:
          rax = bot.enemy_structures({ UnitTypeId.BARRACKS })
          # we have to check if the base exists again, because otherwise this will trigger on game start
          if rax.center.distance_to(enemy_bases.first) > 40 or (now > 75 and rax.empty and enemy_bases.exists):
            # hey bro why your rax so far away?
            known_rushing = True
        if bot.enemy_race == Race.ZERG:
          pool = bot.enemy_structures({ UnitTypeId.SPAWNINGPOOL })
          if now > 120 and pool.exists and enemy_bases.amount < 2:
            known_rushing = True
        if bot.enemy_race == Race.PROTOSS:
          dangers = bot.enemy_structures({ UnitTypeId.PYLON, UnitTypeId.GATEWAY })
          gates = bot.enemy_structures({ UnitTypeId.GATEWAY })
          if dangers.closest_to(bot.start_location).is_closer_than(50, bot.start_location) or \
            (now > 75 and gates.empty and enemy_bases.exists) or \
            gates.amount > 1 and bot.enemy_structures(TECH_STRUCTURES).empty:
            known_rushing = True

      if known_rushing:
        bot.advisor_data.scouting['enemy_is_rushing'] = True
        self.status = ScoutingMissionStatus.COMPLETE
      elif known_not_rushing:
        bot.advisor_data.scouting['enemy_is_rushing'] = False
        self.status = ScoutingMissionStatus.COMPLETE

  def generate_targets(self, bot):
    # if the situation is anything other than a single base in the main,
    # this *might* be hit once but that scout is going home soon
    base = bot.enemy_structures(BaseStructures).first
    def distance_to_enemy(ramp):
      return ramp.top_center.distance_to(base)

    # TODO: figure out ramp better
    likely_main_ramp = min(bot.game_info.map_ramps, key=distance_to_enemy)
    def distance_to_ramp(base):
      return base.distance_to(likely_main_ramp.bottom_center)

    possible_naturals = [ position for position in bot.expansion_locations.keys() if position.is_further_than(1.0, base.position) ]
    likely_natural = min(possible_naturals, key=distance_to_ramp)

    corners = [ Point2([8, 8]), Point2([8, -8]), Point2([-8, -8]), Point2([-8, 8]) ]
    self.targets = list_flatten([[ pos + base.position for pos in corners ], [ likely_natural ] ])

  def on_unit_destroyed(self, tag):
    self.status = ScoutingMissionStatus.FAILED


class ExploreMapMission(ScoutingMission):
  def __init__(self, unit_priority=[ UnitTypeId.OBSERVER, UnitTypeId.ADEPT, UnitTypeId.PROBE ]):
    super().__init__(unit_priority)

  def generate_targets(self, bot):
    self.targets = list(bot.expansion_locations.keys())


class RevealMainMission(ScoutingMission):
  def __init__(self, unit_priority=[ UnitTypeId.OBSERVER, UnitTypeId.ADEPT, UnitTypeId.PROBE ]):
    super().__init__(unit_priority)


class WatchEnemyArmyMission(ScoutingMission):
  def __init__(self, unit_priority=[ UnitTypeId.OBSERVER, UnitTypeId.ADEPT, UnitTypeId.PROBE ]):
    super().__init__(unit_priority)
    self.static_targets = False

  def prerequisite(self, bot):
    return bot.advisor_data.scouting['enemy_is_rushing'] != None

  def adjust_for_safety(self, target, bot):
    if self.retreat_until:
      target = None
      if bot.time >= self.retreat_until and self.unit.shield == self.unit.shield_max:
        self.retreat_until = None
    return target

  def generate_targets(self, bot):
    # what combat units do we know about?
    is_combat_unit = lambda e: (e.type_id not in (UnitTypeId.PROBE, UnitTypeId.DRONE, UnitTypeId.SCV))
    known_enemy_units = Units(bot.advisor_data.scouting['enemy_army'].values(), bot).filter(is_combat_unit)
    seen_enemy_units = bot.enemy_units.filter(is_combat_unit)

    if seen_enemy_units.amount > known_enemy_units.amount / 5:
      self.is_lost = False

    if known_enemy_units.exists:
      enemies_center = known_enemy_units.center
      if self.unit:
        scout = self.unit
        if scout.position.distance_to(enemies_center) < 5 and bot.enemy_units.closer_than(10, scout.position).empty:
          self.is_lost = True
        if self.is_lost:
          # we got some bad intel, boys
          enemy_bases = bot.enemy_structures(BaseStructures)
          if enemy_bases.exists:
            self.targets = [ enemy_bases.furthest_to(scout.position) ]
          else:
            # look man, I just wanna find some bad guys to spy on, why all the hassle
            self.targets = [ pos for pos in bot.enemy_start_locations if bot.state.visibility[Point2([ int(pos.x), int(pos.y) ])] == 0 ]
        else:
          towards_danger = enemies_center - scout.position
          to_the_side = Point2([ towards_danger.y, -towards_danger.x ]) if int(bot.time / 30) % 2 == 0 else Point2([ -towards_danger.y, towards_danger.x ])
          self.targets = [ enemies_center.towards(enemies_center + to_the_side, 4) ]
      else:
        self.targets = [ enemies_center ]
    else:
      self.targets = [ b.position for b in bot.enemy_structures ]


class SupportArmyMission(ScoutingMission):
  def __init__(self, unit_priority=[ UnitTypeId.OBSERVER, UnitTypeId.ADEPT, UnitTypeId.PROBE ]):
    super().__init__(unit_priority)
    self.static_targets = False

  def prerequisite(self, bot):
    return bot.units.exists

  def generate_targets(self, bot):
    # if we're defending
    for objective in bot.strategy_advisor.objectives:
      if isinstance(objective, DefenseObjective) and objective.units.exists and objective.enemies.exists:
        self.targets = [ objective.units.closest_to(objective.enemies.center) ]
        return

    # if we're attacking
    for objective in bot.strategy_advisor.objectives:
      if isinstance(objective, AttackObjective) and objective.units.exists and objective.enemies.exists and objective.status != ObjectiveStatus.RETREATING:
        self.targets = [ objective.units.closest_to(objective.enemies.center) ]
        return

    self.targets = [ bot.rally_point ]

class ExpansionHuntMission(ScoutingMission):
  def __init__(self, unit_priority=[ UnitTypeId.OBSERVER, UnitTypeId.ADEPT, UnitTypeId.PROBE ]):
    super().__init__(unit_priority)

  def prerequisite(self, bot):
    return bot.enemy_structures.exists and bot.time >= 120

  def update_targets(self, bot):
    super().update_targets(bot)
    enemy_bases = bot.enemy_structures(BaseStructures)
    if self.targets and enemy_bases.exists and enemy_bases.closer_than(1.0, self.targets[0]).exists:
      self.next_target(bot)

  def generate_targets(self, bot):
    enemy_bases = [b.position for b in bot.enemy_structures(BaseStructures)]
    our_bases = list(bot.owned_expansions.keys())
    self.targets = [ p for p in bot.expansion_locations.keys() if p not in enemy_bases + our_bases ]


class ProtossScoutingAdvisor(Advisor):
  def __init__(self, manager):
    super().__init__(manager)
    self.missions = [
      FindBasesMission(),
      DetectCheeseMission(),
      ExpansionHuntMission(unit_priority=[ UnitTypeId.ADEPT, UnitTypeId.OBSERVER ]),
      WatchEnemyArmyMission(unit_priority=[ UnitTypeId.ADEPT, UnitTypeId.ZEALOT, UnitTypeId.PROBE ]),
      WatchEnemyArmyMission(unit_priority=[ UnitTypeId.OBSERVER ]),
      WatchEnemyArmyMission(unit_priority=[ UnitTypeId.ADEPTPHASESHIFT ]),
      SupportArmyMission(unit_priority=[ UnitTypeId.OBSERVER ])
    ]
    manager.advisor_data.scouting['enemy_army'] = dict()
    manager.advisor_data.scouting['enemy_is_rushing'] = None

  async def on_unit_destroyed(self, unit):
    self.manager.advisor_data.scouting['enemy_army'].pop(unit, None)
    self.manager.tagged_units.scouting.discard(unit)
    for m in self.missions:
      if m.unit and m.unit.tag == unit:
        m.on_unit_destroyed(unit)

  async def tick(self):
    if self.manager.enemy_race is None:
      if not self.manager.enemy_race == Race.RANDOM:
        self.manager.enemy_race = self.manager.enemy_race
      elif self.manager.enemy_units.exists:
        self.manager.enemy_race = self.manager.enemy_units.random.race

    self.update_tagged_scouts()       # might not need this depending on how reliable on_unit_destroyed is
    self.update_enemy_unit_data()     # tracking every enemy unit we've seen
    await self.evaluate_mission_status()    # make sure all the scouts are safe and on track
    requests = self.audit_structures() + self.build_robotics_units() + await self.build_gateway_units()
    return requests

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

  def update_tagged_scouts(self):
    # remove dead scouts
    self.manager.tagged_units.scouting = { mission.unit.tag for mission in self.missions if mission.status == ScoutingMissionStatus.ACTIVE and mission.unit }

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

    else:
      for unit_type in mission.unit_priority:
        if mission.unit and mission.unit.type_id == unit_type:
          # no unit better than the one we got
          break

        available_units = self.manager.unallocated(unit_type)
        if unit_type == UnitTypeId.PROBE:
          available_units = available_units.filter(lambda probe: probe.is_idle or probe.is_collecting or probe.distance_to(mission.targets[0]) < 40)

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
      print("Releasing probe")
      mineral_field = self.manager.mineral_field.filter(lambda f: any(th.position.is_closer_than(15, f.position) for th in self.manager.townhalls))
      if mineral_field.exists:
        self.manager.do(scout.gather(mineral_field.random))
    else:
      print("Releasing non-probe")
      self.manager.do(scout.move(self.manager.rally_point))

  async def evaluate_mission_status(self):
    now = self.manager.time
    # process active missions first.
    # this allows missions to use each others' scouts if one completes right when the next one starts.
    for mission in sorted(self.missions, key=lambda mission: mission.status, reverse=True):
      mission.evaluate_mission_status(self.manager)
      if mission.status == ScoutingMissionStatus.PENDING:
        continue

      if mission.status >= ScoutingMissionStatus.COMPLETE:
        if mission.unit:
          # this unit might be better than some other scout on its way towards this location
          improvable_missions = [
            m
            for m in self.missions
            if m.status == ScoutingMissionStatus.ACTIVE
            and m.targets
            and m.unit
              and m.unit.type_id == mission.unit.type_id
              and m.unit.position.distance_to(m.targets[0]) < mission.unit.position.distance_to(m.targets[0])
          ]
          if improvable_missions:
            self.release_scout(improvable_missions[0].unit)
            improvable_missions[0].unit = mission.unit
          else:
            self.release_scout(mission.unit)
          # have to do this at the end, it's needed until now
          mission.unit = None
        continue

      mission.update_targets(self.manager)
      if not mission.targets:
        continue

      scout = self.get_scout(mission)
      if not scout:
        continue

      target = mission.targets[0]
      danger = self.find_danger(scout, bonus_range=3)
      # things to do only when there are -- or aren't -- enemies
      if danger.exists:
        # have to await because we check adept abilities
        target = await mission.adjust_for_danger(target, danger, self.manager)
      else:
        target = mission.adjust_for_safety(target, self.manager)

      if target:
        self.manager.do(scout.move(target))
      elif mission.retreat_until and now >= mission.retreat_until:
        self.manager.do(scout.stop())

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
      requests.append(TrainingRequest(UnitTypeId.ADEPT, gateways.ready.idle.first, Urgency.MEDIUMHIGH + 1 - numAdepts))

    return requests