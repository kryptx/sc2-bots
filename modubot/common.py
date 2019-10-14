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

CombatUnits = {
  UnitTypeId.STALKER,
  UnitTypeId.ARCHON,
  UnitTypeId.ZEALOT
}

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
    if bot.shared.warpgate_complete and self.unit_type in TRAIN_INFO[UnitTypeId.WARPGATE]:
      pylon = bot.structures(UnitTypeId.PYLON).closest_to(bot.shared.rally_point)
      pos = pylon.position.to2.random_on_distance([2, 5])
      placement = await bot.find_placement(TRAIN_INFO[UnitTypeId.WARPGATE][self.unit_type]['ability'], pos, placement_step=1)
      if placement:
        return WarpInRequest(self.unit_type, placement, max(1, self.urgency))

    structure_id = list(UNIT_TRAINED_FROM[self.unit_type])
    # Handling warp-ins here has too many problems to count
    structure_id = next(s for s in structure_id if s != UnitTypeId.WARPGATE)
    structures = bot.structures(structure_id)

    if structures.exists:
      requirement = TRAIN_INFO[structure_id][self.unit_type].get('requires_tech_building', None)
      if requirement:
        r_structures = bot.structures(requirement)
        if r_structures.ready.empty:
          # can't build it
          if r_structures.empty and not bot.already_pending(requirement):
            # ooh.
            return StructureRequest(requirement, bot.planner, self.urgency)
          return

    if structures.ready.filter(lambda s: not s.is_active).empty:
      if structure_id not in bot.limits or structures.amount + bot.already_pending(structure_id) < bot.limits[structure_id]:
        return StructureRequest(structure_id, bot.planner, self.urgency)
      return

    return structures.filter(lambda s: not s.is_active).first.train(self.unit_type)

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
          return StructureRequest(requirement, bot.planner, self.urgency)
        return

    warpgates = bot.structures(UnitTypeId.WARPGATE).ready
    for gate in warpgates:
      abilities = await bot.get_available_abilities(gate)
      if AbilityId.WARPGATETRAIN_ZEALOT not in abilities:
        continue
      return gate.warp_in(self.unit_type, self.location)
    in_progress = bot.already_pending(UnitTypeId.GATEWAY) + bot.already_pending(UnitTypeId.WARPGATE)
    if in_progress < 2:
      return StructureRequest(UnitTypeId.GATEWAY, bot.planner, self.urgency)

class BasePlanner():
  def __init__(self, bot):
    self.bot = bot
    self.plans = dict()
    return

  def get_available_positions(self, structure_type):
    raise NotImplementedError("You must override this function")

# this is very much still a PROTOSS structure request
class StructureRequest():
  def __init__(self, structure_type, planner, urgency=Urgency.LOW, force_target=None, near=None):
    self.planner = planner
    self.structure_type = structure_type
    self.urgency = urgency
    self.expense = structure_type
    self.force_target = force_target
    self.near = near
    self.reserve_cost = True

  async def fulfill(self, bot):
    # print(f"fulfilling StructureRequest for {self.expense}, urgency {self.urgency}")
    build_info = TRAIN_INFO[UnitTypeId.PROBE][self.structure_type]
    if 'requires_tech_building' in build_info:
      requirement = build_info['requires_tech_building']
      r_structures = bot.structures(requirement)
      if r_structures.ready.empty:
        if r_structures.empty and not bot.already_pending(requirement): # for this purpose only 1 is ever needed. limits can be ignored.
          return StructureRequest(requirement, self.planner, self.urgency)
        return

    worker = bot.workers.filter(lambda w: w.is_idle or w.is_collecting)
    if not worker.exists:
      worker = bot.workers

    if not worker.exists or (bot.structures(UnitTypeId.PYLON).ready.empty and self.structure_type not in [UnitTypeId.PYLON, UnitTypeId.NEXUS]):
      # womp womp
      return

    if self.force_target:
      return worker.closest_to(self.force_target).build(self.structure_type, self.force_target)

    targets = self.planner.get_available_positions(self.structure_type, near=self.near)
    for location in targets:
      can_build = await bot.can_place(self.structure_type, location)
      if can_build:
        return worker.closest_to(location).build(self.structure_type, location)

    print("Failed to build structure due to poor planning!")
    if not bot.already_pending(UnitTypeId.PYLON):
      targets = self.planner.get_available_positions(UnitTypeId.PYLON)
      for location in targets:
        can_build = await bot.can_place(UnitTypeId.PYLON, location)
        if can_build:
          print("-> Force-built pylon.")
          return worker.closest_to(location).build(UnitTypeId.PYLON, location)
      print("-> Failed to force-build pylon.")
    else:
      print("-> Pylon already pending.")

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
      if (structure_id not in bot.limits) or (structures.amount + bot.already_pending(structure_id) < bot.limits[structure_id]):
        return StructureRequest(structure_id, bot.planner, self.urgency)
      return

    ability = RESEARCH_INFO[structure_id][self.upgrade]['ability']
    return structures.filter(lambda s: not s.is_active).first(ability)

class ExpansionRequest():
  def __init__(self, location, urgency):
    self.reserve_cost = False
    self.urgency = urgency
    self.expense = UnitTypeId.NEXUS
    self.location = location

  async def fulfill(self, bot):
    await bot.expand_now(location=self.location)
    return

def list_diff(first, second):
  second = set(second)
  return [item for item in first if item not in second]

def list_flatten(list_of_lists):
  return [item for sublist in list_of_lists for item in sublist]

def optimism(units, enemy_units):
  return (sum(u.ground_dps * (u.health + u.shield) * (2 if u.is_massive else 1) for u in units) + 300) / (sum(u.ground_dps * (u.health + u.shield) * (2 if u.is_massive else 1) for u in enemy_units) + 300)

def dps(units):
  return sum(u.ground_dps for u in units)

def max_hp(units):
  return sum(u.health_max + u.shield_max for u in units)

def retreat(unit, target):
  return unit.attack(target.position) if unit.weapon_cooldown == 0 else unit.move(target.position)

def is_worker(unit):
  return unit.type_id in [ UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE, UnitTypeId.MULE ]

class OptionsObject(object):
  pass
