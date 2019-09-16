import itertools
import random

import sc2
from sc2.constants import *
from sc2.position import Point2
from sc2.units import Unit, Units

BaseStructures = {
  UnitTypeId.NEXUS,
  UnitTypeId.COMMANDCENTER,
  UnitTypeId.ORBITALCOMMAND,
  UnitTypeId.PLANETARYFORTRESS,
  UnitTypeId.HATCHERY,
  UnitTypeId.LAIR,
  UnitTypeId.HIVE
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

class ObjectiveStatus(enum.IntFlag):
  ALLOCATING = 1,   # Need more units
  STAGING = 2,      # Getting into position and well-arranged
  ACTIVE = 3,       # Attacking
  RETREATING = 4    # boo

class TrainingRequest():
  def __init__(self, unit_type, structure, urgency):
    self.unit_type = unit_type
    self.structure = structure
    self.urgency = urgency
    self.expense = unit_type

  async def fulfill(self, bot):
    return self.structure.train(self.unit_type)

class WarpInRequest():
  def __init__(self, unit_type, warpgate, location, urgency):
    self.unit_type = unit_type
    self.warpgate = warpgate
    self.location = location
    self.urgency = urgency
    self.expense = unit_type

  async def fulfill(self, bot):
    return self.warpgate.warp_in(self.unit_type, self.location)

class BasePlanner():
  def __init__(self, manager):
    self.manager = manager
    self.plans = dict()
    return

  def get_available_positions(self, structure_type):
    raise NotImplementedError("You must override this function")

class StructureRequest():
  def __init__(self, structure_type, planner, urgency=Urgency.LOW, force_target=None):
    self.planner = planner
    self.structure_type = structure_type
    self.urgency = urgency
    self.expense = structure_type
    self.force_target = force_target

  async def fulfill(self, bot):
    worker = bot.workers.filter(lambda w: w.is_idle or w.is_collecting)
    if not worker.exists:
      worker = bot.workers

    if not worker.exists:
      # womp womp
      return

    if self.force_target:
      return worker.closest_to(self.force_target).build(self.structure_type, self.force_target)

    targets = self.planner.get_available_positions(self.structure_type)
    for location in targets:
      can_build = await bot.can_place(self.structure_type, location)
      if can_build:
        return worker.closest_to(location).build(self.structure_type, location)

    print("FAILED TO BUILD STRUCTURE DUE TO POOR PLANNING")

class ResearchRequest():
  def __init__(self, ability, structure, urgency):
    self.ability = ability
    self.structure = structure
    self.urgency = urgency
    self.expense = ability

  async def fulfill(self, bot):
    return self.structure(self.ability)
    # return

class ExpansionRequest():
  def __init__(self, location, urgency):
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

class StrategicObjective():
  def __init__(self, manager, target, urgency, rendezvous=None):
    self.manager = manager
    self.target = target
    self.status = ObjectiveStatus.ALLOCATING
    self.allocated = set()
    self.urgency = urgency
    self.rendezvous = rendezvous
    self.units = Units([], manager)

  @property
  def enemies(self):
    return Units([
      u
      for u in self.manager.advisor_data.scouting['enemy_army'].values()
      if u.ground_dps > 5 or u.air_dps > 0
    ], self.manager)

  def abort(self):
    self.status = ObjectiveStatus.RETREATING

  def tick(self):
    if self.status >= ObjectiveStatus.ALLOCATING:
      self.allocate()
    if self.status == ObjectiveStatus.STAGING:
      self.stage()
    if self.status >= ObjectiveStatus.ACTIVE:
      self.micro()
    if self.status == ObjectiveStatus.RETREATING:
      self.retreat()

  def micro(self):
    if self.units.empty:
      return

    if self.status == ObjectiveStatus.ACTIVE and self.enemies.exists:
      for unit in self.units.idle:
        self.manager.do(unit.attack(self.enemies.closest_to(unit.position)))
    nearby_enemies = self.enemies.closer_than(20, self.units.center)
    if nearby_enemies.exists:
      nearby_threats = nearby_enemies.filter(lambda u: u.ground_dps > 5 or u.air_dps > 0)
      if nearby_threats.amount > self.units.closer_than(20, self.units.center).amount * 1.5:
        self.status = ObjectiveStatus.RETREATING
    return

  def retreat(self):
    print("*****RETREATING*****")
    self.rendezvous = self.staging_base()
    for retreating_unit in self.units:
      if retreating_unit.position.is_further_than(5, self.rendezvous):
        self.manager.do(retreating_unit.move(Point2.center([ self.units.center, self.rendezvous ])))
      elif not retreating_unit.is_idle:
        self.manager.do(retreating_unit.stop())
    if all(unit.position.is_closer_than(10, self.rendezvous) for unit in self.units):
      self.allocated.clear()

  def staging_base(self):
    bases = self.manager.townhalls.filter(lambda nex: self.manager.enemy_units.closer_than(10, nex).empty)
    if not bases.exists:
      return self.manager.start_location
    target_position = self.manager.enemy_units.center if self.manager.enemy_units.exists else self.manager.enemy_start_locations[0]
    return bases.closest_to(target_position).position.towards(self.manager.game_info.map_center, 20)

  def stage(self):
    allocated_units = self.manager.units.tags_in(self.allocated)
    if any(enemy.target_in_range(friendly, bonus_distance=2) for (enemy, friendly) in itertools.product(self.manager.enemy_units, allocated_units)):
      self.rendezvous = allocated_units.center

    if not self.rendezvous:
      for attacking_unit in allocated_units:
        self.manager.do(attacking_unit.attack(self.target.position))
      return

    if all(unit.position.is_closer_than(10, self.rendezvous) for unit in allocated_units):
      for attacking_unit in allocated_units:
        self.manager.do(attacking_unit.attack(self.target.position))
      self.status = ObjectiveStatus.ACTIVE
      return

    for attacking_unit in allocated_units:
      if attacking_unit.type_id == UnitTypeId.STALKER:
        self.manager.do(attacking_unit.attack(self.rendezvous.towards(self.target.position, -3)))
      elif attacking_unit.type_id == UnitTypeId.ZEALOT:
        self.manager.do(attacking_unit.attack(self.rendezvous.towards(self.target.position, 3)))
      elif attacking_unit.type_id == UnitTypeId.ARCHON:
        self.manager.do(attacking_unit.attack(self.rendezvous))

  def allocate(self):
    combat_units = {
      UnitTypeId.STALKER,
      UnitTypeId.ARCHON,
      UnitTypeId.ZEALOT
    }
    complete = False
    enemy_units = self.enemies
    print(str(enemy_units.amount) + " enemy units relevant for this objective")
    already_allocated_units = self.manager.units.tags_in(self.allocated)
    needed_units = int(enemy_units.amount - already_allocated_units.amount)
    wanted_units = max(needed_units, self.manager.units(combat_units).amount)
    if wanted_units <= 0:
      complete = True
    else:
      usable_units = self.manager.unallocated(combat_units, self.urgency)
      if usable_units.amount >= wanted_units:
        adding_units = set(unit.tag for unit in usable_units.closest_n_units(self.target.position, wanted_units))
        for objective in self.manager.strategy_advisor.objectives:
          objective.allocated.difference_update(adding_units)
        self.allocated = self.allocated.union(adding_units)
        if len(self.allocated) >= needed_units or self.manager.supply_used >= 196 and len(self.allocated) >= 40:
          complete = True

    if complete:
      if self.status == ObjectiveStatus.ALLOCATING:
        self.status = ObjectiveStatus.STAGING

    self.units = self.manager.units.tags_in(self.allocated)
    print("objective has allocated " + str(self.units.amount) + " units")
    return

class AttackObjective(StrategicObjective):
  def __init__(self, manager, target, urgency=Urgency.MEDIUM, rendezvous=None):
    super().__init__(manager, target, urgency, rendezvous)
    print("creating attack objective")

  def is_complete(self):
    completed = self.manager.enemy_structures.closer_than(5, self.target.position).empty or \
      self.units.empty or \
      self.status == ObjectiveStatus.RETREATING and all(unit.position.is_closer_than(10, self.rendezvous) for unit in self.units)
    if completed:
      print("attack objective complete")
    return completed

class DefenseObjective(StrategicObjective):
  def __init__(self, manager, target, urgency=Urgency.HIGH, rendezvous=None):
    super().__init__(manager, target, urgency, rendezvous)
    print("creating defense objective")

  def is_complete(self):
    completed = self.manager.structures.tags_in([ self.target.tag ]).empty or \
      self.manager.enemy_units.closer_than(30, self.target.position).empty
    if completed:
      print("defense objective complete")
    return completed

  @property
  def enemies(self):
    return Units(self.manager.advisor_data.scouting['enemy_army'].values(), self.manager).closer_than(30, self.target.position)
