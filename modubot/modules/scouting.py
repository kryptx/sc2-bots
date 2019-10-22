import asyncio
import random

import sc2
from sc2 import Race
from sc2.constants import *
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.position import Point2
from sc2.units import Units

from modubot.common import Urgency, TrainingRequest, StructureRequest, BaseStructures, list_diff, list_flatten
from modubot.modules.module import BotModule
from modubot.scouting.mission import ScoutingMissionStatus


class ScoutManager(BotModule):
  def __init__(self, bot, missions=[], retreat_while=lambda scout: False):
    super().__init__(bot)
    self.missions = missions
    self.retreat_while = retreat_while
    self.cancel_shades = dict()
    bot.shared.enemy_race = None
    bot.shared.enemy_is_rushing = None
    bot.shared.scouts = set()

  async def on_unit_destroyed(self, unit):
    for m in self.missions:
      if m.unit and m.unit.tag == unit:
        await m.on_unit_destroyed(unit)

  async def on_step(self, iteration):
    self.abort_adept_teleports()
    if self.shared.enemy_race is None:
      if self.enemy_race != Race.Random:
        self.shared.enemy_race = self.enemy_race
      elif self.enemy_units.exists:
        self.shared.enemy_race = self.enemy_units.random.race

    self.shared.scouts = self.units.tags_in(self.allocated)

    await self.evaluate_mission_status()    # make sure all the scouts are safe and on track
    requests = self.request_needed_units()
    return requests

  @property
  def allocated(self):
    return { mission.unit.tag
             for mission in self.missions
             if mission.unit and mission.status == ScoutingMissionStatus.ACTIVE }

  @property
  def urgency(self):
    return Urgency.MEDIUMHIGH

  def get_scout(self, mission):
    if mission.unit:
      scouts = self.bot.units.tags_in([ mission.unit.tag ])
      mission.unit = scouts.first if scouts.exists else None

    for unit_type in mission.unit_priority:
      if mission.unit and mission.unit.type_id == unit_type:
        # no unit better than the one we got
        break

      available_units = self.unallocated(unit_type)
      if unit_type == self.shared.common_worker:
        available_units = available_units.filter(lambda w: w.is_idle or w.is_collecting or w.distance_to(mission.targets[0]) < 40)

      if available_units.exists:
        if mission.unit:
          self.log.info(f"Removing {mission.unit.type_id} from {type(mission).__name__} to replace:")
          self.release_scout(mission.unit)
        self.log.info(f"Assigning {unit_type} to {type(mission).__name__}")
        mission.unit = available_units.closest_to(mission.targets[0])
        break

    return mission.unit

  def release_scout(self, scout):
    if scout.type_id == self.shared.common_worker:
      print("Releasing worker")
      mineral_field = self.mineral_field.filter(lambda f: any(th.position.is_closer_than(15, f.position) for th in self.townhalls))
      if mineral_field.exists:
        self.do(scout.gather(mineral_field.random))
    else:
      print("Releasing non-worker")
      self.do(scout.move(self.shared.rally_point))

  async def evaluate_mission_status(self):
    now = self.time
    # process active missions first.
    # this allows missions to use each others' scouts if one completes right when the next one starts.
    for mission in sorted(self.missions, key=lambda mission: mission.status, reverse=True):
      mission.evaluate_mission_status()
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

      mission.update_targets()
      if not mission.targets:
        continue

      scout = self.get_scout(mission)
      if not scout:
        continue

      target = mission.targets[0]
      danger = self.find_danger(scout, bonus_range=3)
      # things to do only when there are -- or aren't -- enemies
      if danger.exists:
        now = self.time
        scout = self.units.tags_in([ mission.unit.tag ]).first
        if scout.is_flying:
          target = scout.position.towards(danger.center, -2)
        else:
          target = self.shared.rally_point

        if scout.type_id == UnitTypeId.ADEPT:
          abilities = await self.get_available_abilities(scout)
          if AbilityId.ADEPTPHASESHIFT_ADEPTPHASESHIFT in abilities:
            self.do(scout(AbilityId.ADEPTPHASESHIFT_ADEPTPHASESHIFT, scout.position))
            mission.retreat_until = now + 13
            # TODO this is the wrong self
            self.cancel_shades[mission.unit.tag] = now + 6

      if mission.retreat_while(scout):
        if mission.static_targets and mission.retreat_until and now >= mission.retreat_until:
          # they came after the scout while we were waiting for its shield to recharge
          mission.next_target()
        # at this point, the timer is only for the purpose of whether to give up on the current target
        mission.retreat_until = max(mission.retreat_until, now) if mission.retreat_until else now

      if danger.empty and mission.retreat_until and mission.retreat_until >= now:
        target = None

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

  def request_needed_units(self):
    requests = []
    active_missions = [ m for m in self.missions if m.status == ScoutingMissionStatus.ACTIVE ]
    for mission in active_missions:
      urgency = Urgency.MEDIUM
      for unit_type in mission.unit_priority:
        if mission.unit and mission.unit.type_id == unit_type:
          break
        if unit_type not in UNIT_TRAINED_FROM:
          continue
        requests.append(TrainingRequest(unit_type, max(1, urgency)))
    return requests

  def abort_adept_teleports(self):
    if not self.cancel_shades:
      return

    to_cancel = [tag for tag in self.cancel_shades.keys() if self.cancel_shades[tag] <= self.time]
    for adept in self.units.tags_in(to_cancel):
      self.do(adept(AbilityId.CANCEL_ADEPTPHASESHIFT))

    for tag in to_cancel:
      self.cancel_shades.pop(tag)