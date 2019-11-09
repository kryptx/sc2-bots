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

class TrainingRequest():
  def __init__(self, unit_type, urgency):
    self.reserve_cost = True
    self.unit_type = unit_type
    self.urgency = urgency
    self.expense = unit_type

  async def fulfill(self, bot):
    if getattr(bot.shared, 'warpgate_complete', False) and self.unit_type in TRAIN_INFO[UnitTypeId.WARPGATE]:
      pylon = bot.structures(UnitTypeId.PYLON).ready.closest_to(bot.shared.rally_point)
      pos = pylon.position.to2.random_on_distance([2, 5])
      placement = await bot.find_placement(TRAIN_INFO[UnitTypeId.WARPGATE][self.unit_type]['ability'], pos, placement_step=1)
      if placement:
        return WarpInRequest(self.unit_type, placement, max(1, self.urgency))

    # yes, this can be abbreviated pretty easily, but it comes at a great cost to readability
    creating_type = self.unit_type
    eligible_creators = set(UNIT_TRAINED_FROM[creating_type])
    eligible_creators.discard(UnitTypeId.WARPGATE)

    while UnitTypeId.LARVA not in eligible_creators and bot.units(eligible_creators).empty and bot.structures(eligible_creators).empty:
      creating_type = list(eligible_creators)[0]
      eligible_creators = [ s for s in list(UNIT_TRAINED_FROM[creating_type]) if s != UnitTypeId.WARPGATE ]

    creators = bot.units(eligible_creators) if bot.units(eligible_creators).exists else bot.structures(eligible_creators)

    if creators.exists:
      creator_type = creators.first.type_id
      bot.log.info(f"Checking tech requirements to create {creating_type}")
      requirement = TRAIN_INFO[creator_type][creating_type].get('requires_tech_building', None)
      if requirement:
        r_structures = bot.structures(requirement)
        if r_structures.ready.empty:
          # can't build it
          if r_structures.empty and not bot.already_pending(requirement):
            # ooh.
            return StructureRequest(requirement, self.urgency)
          return
    else:
      creator_type = list(eligible_creators)[0]

    if creators.ready.filter(lambda c: not c.is_active).exists:
      return creators.ready.filter(lambda c: not c.is_active).random(TRAIN_INFO[creator_type][creating_type]['ability'])

    if creators.ready.empty:
      if creator_type != UnitTypeId.LARVA and (
        creator_type not in bot.limits or
        creators.amount + bot.already_pending(creator_type) < bot.limits[creator_type]()
      ):
        return StructureRequest(creator_type, self.urgency)
      return

    return creators.ready.first.train(self.unit_type)

class WarpInRequest():
  def __init__(self, unit_type, location, urgency):
    self.reserve_cost = True
    self.unit_type = unit_type
    self.location = location
    self.urgency = urgency
    self.expense = unit_type

  async def fulfill(self, bot):
    requirement = TRAIN_INFO[UnitTypeId.GATEWAY][self.unit_type].get('requires_tech_building', None)
    if requirement:
      r_structures = bot.structures(requirement)
      if r_structures.ready.empty:
        # can't build it
        if r_structures.empty and not bot.already_pending(requirement):
          # ooh.
          return StructureRequest(requirement, self.urgency)
        return

    warpgates = bot.structures(UnitTypeId.WARPGATE).ready
    for gate in warpgates:
      abilities = await bot.get_available_abilities(gate)
      if AbilityId.WARPGATETRAIN_ZEALOT not in abilities:
        continue
      return gate.warp_in(self.unit_type, self.location)
    in_progress = bot.already_pending(UnitTypeId.GATEWAY) + bot.already_pending(UnitTypeId.WARPGATE)
    if in_progress < 2:
      return StructureRequest(UnitTypeId.GATEWAY, self.urgency)

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

class StructureRequest():
  def __init__(self, structure_type, urgency=Urgency.LOW, force_target=None, near=None):
    self.structure_type = structure_type
    self.urgency = urgency
    self.expense = structure_type
    self.force_target = force_target
    self.near = near
    self.reserve_cost = True

  async def fulfill(self, bot):
    # short circuit for creep tumor spreading
    # Assumes a module maintains a set of tags in `shared.unused_tumors`
    if self.structure_type == UnitTypeId.CREEPTUMOR:
      # first try to spread from an existing one
      ready_tumors = bot.structures.tags_in(bot.shared.unused_tumors).ready
      if ready_tumors.empty:
        capable_queens = bot.units(UnitTypeId.QUEEN).filter(lambda q: q.energy > 30)
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

    # print(f"fulfilling StructureRequest for {self.expense}, urgency {self.urgency}")
    if bot.shared.common_worker not in UNIT_TRAINED_FROM[self.structure_type]:
      # this structure is "morphed" from another structure (Lair, Hive, Orbital Command, Planetary Fortress, Greater Spire, etc)
      structure_root = list(UNIT_TRAINED_FROM[self.structure_type])[0]
      if bot.structures(structure_root).ready.empty:
        return StructureRequest(structure_root, self.urgency)
      else:
        return bot.structures(structure_root).first(TRAIN_INFO[structure_root][self.structure_type]['ability'])

    build_info = TRAIN_INFO[bot.shared.common_worker][self.structure_type]
    if 'requires_tech_building' in build_info:
      requirement = build_info['requires_tech_building']
      r_structures = bot.structures(requirement)
      if r_structures.ready.empty:
        if r_structures.empty and not bot.already_pending(requirement): # for this purpose only 1 is ever needed. limits can be ignored.
          return StructureRequest(requirement, self.urgency)
        return

    workers = bot.workers.filter(lambda w: w.is_idle or w.is_collecting)
    if not workers.exists:
      workers = bot.workers

    if not workers.exists or not bot.planner.may_place(self.structure_type):
      # womp womp
      return

    if self.force_target:
      return workers.closest_to(self.force_target).build(self.structure_type, self.force_target)

    targets = bot.planner.get_available_positions(self.structure_type, near=self.near)
    print(f"{len(targets)} found for {self.structure_type}")
    for location in targets:
      can_build = await bot.can_place(self.structure_type, location)
      if can_build:
        return workers.closest_to(location).build(self.structure_type, location)

    print("Failed to build structure due to poor planning!")
    await bot.planner.increase_buildable_area(workers)

class ResearchRequest():
  def __init__(self, upgrade, urgency):
    self.reserve_cost = False
    self.upgrade = upgrade
    self.urgency = urgency
    self.expense = upgrade

  async def fulfill(self, bot):
    # print(f"fulfilling ResearchRequest for {self.expense}, urgency {self.urgency}")
    structure_id = UPGRADE_RESEARCHED_FROM[self.upgrade]
    structures = bot.structures(structure_id)
    if structures.ready.filter(lambda s: not s.is_active).empty:
      if (structure_id not in bot.limits) or (structures.amount + bot.already_pending(structure_id) < bot.limits[structure_id]()):
        return StructureRequest(structure_id, self.urgency)
      return

    ability = RESEARCH_INFO[structure_id][self.upgrade]['ability']
    return structures.filter(lambda s: not s.is_active).first(ability)

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
