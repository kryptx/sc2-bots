import asyncio
import random

import sc2
from sc2.constants import *
from sc2.units import Units
from sc2.position import Point2

from modubot.common import Urgency, WarpInRequest, TrainingRequest, StructureRequest, BaseStructures, list_diff, list_flatten
from modubot.modules.module import BotModule
from modubot.scouting.mission import ScoutingMissionStatus, Race

class ScoutManager(BotModule):
  def __init__(self, bot, missions=[]):
    super().__init__(bot)
    self.missions = missions
    bot.shared.enemy_race = None
    bot.shared.enemy_is_rushing = None
    bot.shared.scouts = set()

  async def on_unit_destroyed(self, unit):
    for m in self.missions:
      if m.unit and m.unit.tag == unit:
        await m.on_unit_destroyed(unit)

  async def on_step(self, iteration):
    if self.shared.enemy_race is None:
      if self.enemy_race != Race.RANDOM:
        self.shared.enemy_race = self.enemy_race
      elif self.enemy_units.exists:
        self.shared.enemy_race = self.enemy_units.random.race

    self.shared.scouts = self.units.tags_in(self.allocated)

    await self.evaluate_mission_status()    # make sure all the scouts are safe and on track
    requests = self.build_robotics_units() + await self.build_gateway_units()
    return requests

  @property
  def allocated(self):
    return { mission.unit.tag
             for mission in self.missions
             if mission.unit and mission.status == ScoutingMissionStatus.ACTIVE }

  def get_scout(self, mission):
    if mission.unit:
      scouts = self.bot.units.tags_in([ mission.unit.tag ])
      mission.unit = scouts.first if scouts.exists else None

    for unit_type in mission.unit_priority:
      if mission.unit and mission.unit.type_id == unit_type:
        # no unit better than the one we got
        break

      available_units = self.unallocated(unit_type)
      if unit_type == UnitTypeId.PROBE:
        available_units = available_units.filter(lambda probe: probe.is_idle or probe.is_collecting or probe.distance_to(mission.targets[0]) < 40)

      if available_units.exists:
        if mission.unit:
          self.log.info(f"Removing {mission.unit.type_id} from {type(mission).__name__} to replace:")
          self.release_scout(mission.unit)
        self.log.info(f"Assigning {unit_type} to {type(mission).__name__}")
        mission.unit = available_units.closest_to(mission.targets[0])
        break

    return mission.unit

  def release_scout(self, scout):
    if scout.type_id == UnitTypeId.PROBE:
      print("Releasing probe")
      mineral_field = self.mineral_field.filter(lambda f: any(th.position.is_closer_than(15, f.position) for th in self.townhalls))
      if mineral_field.exists:
        self.do(scout.gather(mineral_field.random))
    else:
      print("Releasing non-probe")
      self.do(scout.move(self.shared.rally_point))

  async def evaluate_mission_status(self):
    now = self.time
    # process active missions first.
    # this allows missions to use each others' scouts if one completes right when the next one starts.
    for mission in sorted(self.missions, key=lambda mission: mission.status, reverse=True):
      mission.evaluate_mission_status(self)
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

      mission.update_targets(self)
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
        target = await mission.adjust_for_danger(target, danger, self)
      else:
        target = mission.adjust_for_safety(target, self)

      if target:
        self.do(scout.move(target))
      elif mission.retreat_until and now >= mission.retreat_until:
        self.do(scout.stop())

  def find_danger(self, scout, bonus_range=1):
    if scout.type_id == UnitTypeId.ADEPTPHASESHIFT:
      # I ain't afraid
      return Units([], self)

    enemies = self.enemy_units + self.enemy_structures
    enemies_that_could_hit_scout = enemies.filter(lambda e: (e.ground_dps > 5 or e.air_dps > 5) and e.target_in_range(scout, bonus_distance=bonus_range))
    return enemies_that_could_hit_scout

  def build_robotics_units(self):
    requests = []
    numObservers = self.units(UnitTypeId.OBSERVER).amount

    urgency = Urgency.MEDIUMLOW
    if numObservers < 1:
      urgency = Urgency.MEDIUM
    if numObservers < 2:
      requests.append(TrainingRequest(UnitTypeId.OBSERVER, urgency))
      numObservers += 1

    return requests

  async def build_gateway_units(self):
    requests = []
    numAdepts = self.units(UnitTypeId.ADEPT).amount
    if numAdepts >= 2:
      return requests

    if self.shared.warpgate_complete:
      pos = self.structures(UnitTypeId.PYLON).closest_to(self.shared.rally_point).position.to2.random_on_distance([2, 5])
      placement = await self.find_placement(AbilityId.TRAINWARP_ADEPT, pos, placement_step=1)
      if not placement is None:
        requests.append(WarpInRequest(UnitTypeId.ADEPT, placement, Urgency.HIGH))

    else:
      requests.append(TrainingRequest(UnitTypeId.ADEPT, Urgency.MEDIUM + 1 - numAdepts))

    return requests