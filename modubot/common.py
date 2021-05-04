import asyncio
import itertools
import random

import sc2
from sc2.constants import *
from sc2.position import Point2
from sc2.units import Unit, Units
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_research_abilities import RESEARCH_INFO

BaseStructures = {
  UnitTypeId.NEXUS,
  UnitTypeId.COMMANDCENTER,
  UnitTypeId.ORBITALCOMMAND,
  UnitTypeId.PLANETARYFORTRESS,
  UnitTypeId.HATCHERY,
  UnitTypeId.LAIR,
  UnitTypeId.HIVE
}

class LoggerWithFields(object):
  def __init__(self, logger, fields):
    self.logger = logger
    self.fields = fields

  def withFields(self, fields):
    return LoggerWithFields(self.logger, {**self.fields, **fields})

  def __getattr__(self, name):
    if name not in ['debug','info','warn','warning','error']:
      return getattr(self.logger, name)

    def log_with_fields(msg):
      if isinstance(msg, str):
        msg = {"message": msg}

      getattr(self.logger, name)({"level": name, **msg, **self.fields})

    return log_with_fields

def median_position(positions=[]):
  xes = sorted(pos.x for pos in positions)
  ys = sorted(pos.y for pos in positions)
  mid = int(len(positions) / 2)
  return Point2([ xes[mid], ys[mid] ])

class Urgency(enum.IntFlag):
  NONE = 0,       # don't do this
  VERYLOW = 1,    # Totally fine if it never happens
  LOW = 2,        # Whenever we have an excess
  MEDIUMLOW = 3,  # sometime relatively soon
  MEDIUM = 4,     # As a matter of course
  MEDIUMHIGH = 5, # soon
  HIGH = 6,       # maybe put some other things off
  VERYHIGH = 7,   # definitely put some other things off
  EXTREME = 8,    # absolutely do this right now
  LIFEORDEATH = 9 # if you can't do this, you might as well surrender

class BasePlanner():
  def __init__(self, bot):
    self.bot = bot
    self.plans = dict()
    return

  def __getattr__(self, name):
    return getattr(self.bot, name)

  def may_place(self, structure_type):
    return True

  def get_available_positions(self, structure_type):
    raise NotImplementedError("You must override this function")

  def increase_buildable_area(self):
    raise NotImplementedError("Your base planner could not find anywhere to put the structure. Implement the increase_buildable_area function in your base planner.")


class BuildRequest():
  def __init__(self, expense, urgency=Urgency.LOW, force_target=None, near=None):
    self.expense = expense
    self.urgency = urgency
    self.force_target = force_target
    self.near = near

  async def fulfill(self, bot):
    if self.expense not in UNIT_TRAINED_FROM:
      # probably larva. This means we just don't have enough larva for what we want.
      return

    # let's just keep this somewhere else.
    if self.expense == UnitTypeId.CREEPTUMOR:
      await self.fulfill_creep_tumor_request(bot)
      return

    all_units = bot.units + bot.structures
    creator_types = { t for t in UNIT_TRAINED_FROM[self.expense] if t != UnitTypeId.WARPGATE }
    root_type = all_units(creator_types).first.type_id if all_units(creator_types).exists else list(creator_types)[0]
    ability = TRAIN_INFO[root_type][self.expense]['ability']
    builders = all_units(root_type)

    if (self.expense in bot.limits and all_units(self.expense).amount + bot.already_pending(self.expense) >= bot.limits[self.expense]()):
      return

    if 'required_building' in TRAIN_INFO[root_type][self.expense]:
      dependency_type = TRAIN_INFO[root_type][self.expense]['required_building']
      dependents = all_units(dependency_type)
      if dependents.empty and not bot.already_pending(dependency_type):
        return BuildRequest(dependency_type, self.urgency)

      if dependents.ready.empty:
        return

    if bot.shared.common_worker not in creator_types:
      # this is either a unit, or a structure which is "morphed" from another structure
      # (Lair, Hive, Orbital Command, Planetary Fortress, Greater Spire, Lurker Den)

      if getattr(bot.shared, 'warpgate_complete', False) and self.expense in TRAIN_INFO[UnitTypeId.WARPGATE]:
        return await self.fulfill_by_warp_in(bot)

      selected_builder = None
      for builder in builders.filter(lambda b: not b.is_active):
        abilities = await bot.get_available_abilities(builder)
        if ability in abilities:
          selected_builder = builder
          break

      if not selected_builder:
        return BuildRequest(root_type, self.urgency)

      return selected_builder(ability)

    # If we get this far, we are creating a structure with a worker.
    workers = bot.workers.filter(lambda w: w.is_idle or w.is_collecting)
    if not workers.exists:
      workers = bot.workers

    if not workers.exists or not bot.planner.may_place(self.expense):
      # womp womp
      return

    if self.force_target:
      return workers.closest_to(self.force_target).build(self.expense, self.force_target)

    targets = bot.planner.get_available_positions(self.expense, near=self.near)
    for location in targets:
      can_build = await bot.can_place_single(self.expense, location)
      if can_build:
        return workers.closest_to(location).build(self.expense, location)

    bot.log.warning("Failed to build structure due to poor planning!")
    await bot.planner.increase_buildable_area(workers)

  async def fulfill_by_warp_in(self, bot):
    pylon = bot.structures(UnitTypeId.PYLON).ready.closest_to(bot.shared.rally_point)
    pos = pylon.position.to2.random_on_distance([2, 5])
    placement = await bot.find_placement(TRAIN_INFO[UnitTypeId.WARPGATE][self.expense]['ability'], pos, placement_step=1)
    if placement:
      warpgates = bot.structures(UnitTypeId.WARPGATE).ready
      for gate in warpgates:
        abilities = await bot.get_available_abilities(gate)
        # if we can't warp in either sentry or zealot, then the gate is busy
        # if we only can't warp in zealot, we might have enough gas for sentry or HT
        if all(a not in abilities for a in [AbilityId.WARPGATETRAIN_SENTRY, AbilityId.WARPGATETRAIN_ZEALOT]):
          continue
        return gate.warp_in(self.expense, placement)
      # if we got here, there weren't enough warpgates
      in_progress = bot.already_pending(UnitTypeId.GATEWAY) + bot.already_pending(UnitTypeId.WARPGATE)
      if in_progress < 2:
        return BuildRequest(UnitTypeId.GATEWAY, self.urgency)

  async def fulfill_creep_tumor_request(self, bot):
    # first try to spread from an existing one
    ready_tumors = bot.structures.tags_in(bot.shared.unused_tumors)
    if ready_tumors.empty:
      capable_queens = bot.units(UnitTypeId.QUEEN).idle.filter(lambda q: q.energy > 40)
      if capable_queens.exists:
        target = bot.planner.queen_tumor_position()
        if target:
          bot.do(capable_queens.closest_to(target)(AbilityId.BUILD_CREEPTUMOR_QUEEN, target))
      return

    for tumor in ready_tumors:
      tumor_abilities = await bot.get_available_abilities(tumor)
      if AbilityId.BUILD_CREEPTUMOR_TUMOR in tumor_abilities:
        target = bot.planner.tumor_tumor_position(tumor)
        if target:
          bot.do(tumor(AbilityId.BUILD_CREEPTUMOR_TUMOR, target))

        bot.shared.unused_tumors.discard(tumor.tag)

class ResearchRequest():
  def __init__(self, upgrade, urgency):
    self.reserve_cost = False
    self.upgrade = upgrade
    self.urgency = urgency
    self.expense = upgrade

  async def fulfill(self, bot):
    bot.log.debug(f"fulfilling ResearchRequest for {self.expense}, urgency {self.urgency}")
    structure_id = UPGRADE_RESEARCHED_FROM[self.upgrade]
    structures = bot.structures(structure_id)
    if structures.ready.filter(lambda s: not s.is_active).empty:
      return BuildRequest(structure_id, self.urgency)

    ability = RESEARCH_INFO[structure_id][self.upgrade]['ability']
    prerequisite = structure_id
    if 'required_building' in RESEARCH_INFO[structure_id][self.upgrade]:
      prerequisite = RESEARCH_INFO[structure_id][self.upgrade]['required_building']

    dependents = bot.structures(prerequisite)
    if dependents.empty and not bot.already_pending(prerequisite):
      return BuildRequest(prerequisite, self.urgency)

    if dependents.ready.empty:
      return

    return structures.ready.filter(lambda s: not s.is_active).first(ability)

def list_diff(first, second):
  second = set(second)
  return [item for item in first if item not in second]

def list_flatten(list_of_lists):
  return [item for sublist in list_of_lists for item in sublist]

def optimism(units, enemy_units):
  return (sum(u.ground_dps * (u.health + u.shield) * (2 if u.is_massive else 1) for u in units) + 1000) /\
         (sum(u.ground_dps * (u.health + u.shield) * (2 if u.is_massive else 1) for u in enemy_units) + 1000)

def dps(units):
  return sum(u.ground_dps for u in units)

def max_hp(units):
  return sum(u.health_max + u.shield_max for u in units)

def retreat(unit, target):
  return unit.attack(target.position) if unit.weapon_cooldown == 0 else unit.move(target.position)

def is_worker(unit):
  return unit.type_id in [ UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE, UnitTypeId.MULE, UnitTypeId.OVERLORD ]

class OptionsObject(object):
  pass
