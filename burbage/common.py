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

def optimism(units, enemy_units):
  return float(dps(units) * max_hp(units) + 1000) / float(dps(enemy_units) * max_hp(enemy_units) + 1000)

def dps(units):
  return sum(u.ground_dps for u in units)

def max_hp(units):
  return sum(u.health_max + u.shield_max for u in units)

class StrategicObjective():
  def __init__(self, manager, urgency, rendezvous=None):
    self.manager = manager
    self.status = ObjectiveStatus.ALLOCATING
    self.status_since = manager.time
    self.allocated = set()
    self.urgency = urgency
    self.rendezvous = rendezvous
    self.units = Units([], manager)
    self.last_seen = 1

  def log(self, msg):
    print(f"{type(self).__name__} {msg}")

  @property
  def enemies(self):
    return Units([
      u
      for u in self.manager.advisor_data.scouting['enemy_army'].values()
      if u.type_id not in [ UnitTypeId.PROBE, UnitTypeId.DRONE, UnitTypeId.SCV ]
    ], self.manager)

  def abort(self):
    self.status = ObjectiveStatus.RETREATING
    self.status_since = self.manager.time

  def tick(self):
    self.last_seen = self.manager.time if self.enemies.exists else self.last_seen
    if self.status >= ObjectiveStatus.ALLOCATING:
      self.allocate()
    if self.status == ObjectiveStatus.STAGING:
      self.stage()
    if self.status >= ObjectiveStatus.ACTIVE:
      self.micro()
    if self.status == ObjectiveStatus.RETREATING:
      self.retreat()

  def retreat_unit(self, unit, target):
    if unit.type_id == UnitTypeId.STALKER and unit.weapon_cooldown == 0:
      self.manager.do(unit.attack(target))
    else:
      self.manager.do(unit.move(target))

  def wanted_units(self):
    return self.manager.units(CombatUnits).amount - self.units.amount

  def micro(self):
    if self.units.empty:
      self.log("no units to micro")
      return

    if self.status == ObjectiveStatus.ACTIVE:
      visible_enemies = self.manager.enemy_units.filter(lambda u: u.tag in self.enemies)
      for unit in self.units:
        if visible_enemies.exists:
          self.manager.do(unit.attack(self.enemies.closest_to(unit.position)))
        else:
          self.manager.do(unit.attack(self.manager.enemy_structures.closest_to(unit.position).position))

    nearby_enemies = {
      enemy_unit
      for (friendly_unit, enemy_unit) in itertools.product(self.units, self.enemies)
      if enemy_unit.position.is_closer_than(15, friendly_unit)
    }
    if optimism(self.units, nearby_enemies) < 1:
      self.log(f"*****RETREATING***** {len(nearby_enemies)} enemies, {self.units.amount} units")
      self.status = ObjectiveStatus.RETREATING
      self.status_since = self.manager.time
    return

  def retreat(self):
    self.rendezvous = self.staging_base()
    for retreating_unit in self.units:
      if retreating_unit.position.is_further_than(5, self.rendezvous):
        self.retreat_unit(retreating_unit, Point2.center([ self.units.center, self.rendezvous ]))
    if all(unit.position.is_closer_than(10, self.rendezvous) for unit in self.units):
      self.allocated.clear()

  def staging_base(self):
    bases = self.manager.townhalls.filter(lambda nex: self.manager.enemy_units.closer_than(10, nex).empty)
    if not bases.exists:
      return self.manager.start_location
    target_position = self.manager.enemy_units.center if self.manager.enemy_units.exists else self.manager.enemy_start_locations[0]
    return bases.closest_to(target_position).position.towards(self.manager.start_location, 5)

  def stage(self):
    allocated_units = self.units

    if allocated_units.amount > self.enemies.amount * 6:
      for attacking_unit in allocated_units:
        self.manager.do(attacking_unit.attack(self.target.position))
      self.log("Upgrading to active due to apparent overwhelming advantage")
      self.status = ObjectiveStatus.ACTIVE
      self.status_since = self.manager.time
      return

    if self.manager.time - self.status_since > 3:
      for attacking_unit in allocated_units:
        self.manager.do(attacking_unit.attack(self.target.position))
      self.log("Upgrading to active because staging phase lasted over 3 seconds")
      self.status = ObjectiveStatus.ACTIVE
      self.status_since = self.manager.time
      return

    if not self.rendezvous:
      for attacking_unit in allocated_units:
        self.manager.do(attacking_unit.attack(self.target.position))
      if any(enemy.target_in_range(friendly, bonus_distance=3) for (enemy, friendly) in itertools.product(self.manager.enemy_units, allocated_units)):
        self.rendezvous = allocated_units.center

    if not self.rendezvous:
      return

    if all(unit.position.is_closer_than(10, self.rendezvous) for unit in allocated_units):
      for attacking_unit in allocated_units:
        self.manager.do(attacking_unit.attack(self.target.position))
      self.log("Upgrading to active after rendezvous")
      self.status = ObjectiveStatus.ACTIVE
      self.status_since = self.manager.time
      return

    for attacking_unit in allocated_units:
      if attacking_unit.type_id == UnitTypeId.STALKER:
        self.manager.do(attacking_unit.move(self.rendezvous.towards(self.target.position, -3)))
      elif attacking_unit.type_id == UnitTypeId.ZEALOT:
        self.manager.do(attacking_unit.move(self.rendezvous.towards(self.target.position, 3)))
      elif attacking_unit.type_id == UnitTypeId.ARCHON:
        self.manager.do(attacking_unit.move(self.rendezvous))

  def allocate(self):
    fully_allocated = False
    enemy_units = self.enemies
    already_allocated_units = self.manager.units.tags_in(self.allocated)
    needed_units = int(enemy_units.amount - already_allocated_units.amount)
    wanted_units = self.wanted_units()
    if wanted_units <= 0:
      fully_allocated = True
    else:
      usable_units = self.manager.unallocated(CombatUnits, self.urgency)
      if usable_units.amount >= needed_units:
        adding_units = set(unit.tag for unit in usable_units.closest_n_units(self.target.position, wanted_units))
        for objective in self.manager.strategy_advisor.objectives:
          objective.allocated.difference_update(adding_units)
        self.allocated = self.allocated.union(adding_units)
        if len(self.allocated) >= needed_units or self.manager.supply_used >= 196 and len(self.allocated) >= 40:
          fully_allocated = True

    if fully_allocated:
      if self.status == ObjectiveStatus.ALLOCATING:
        self.log("Upgraded to staging")
        self.status = ObjectiveStatus.STAGING
        self.status_since = self.manager.time

    self.units = self.manager.units.tags_in(self.allocated)
    # noisy, but possibly informative
    # self.log(f"{self.units.amount} units allocated for {self.enemies.amount} known enemies")
    return

class AttackObjective(StrategicObjective):
  def __init__(self, manager, target, urgency=Urgency.MEDIUM, rendezvous=None):
    super().__init__(manager, urgency, rendezvous)
    self.target = target
    self.log("creating attack objective")

  def is_complete(self):
    completed = False
    if self.units.empty:
      completed = True
      self.log("completed because it has no units")
    elif self.status == ObjectiveStatus.RETREATING and all(unit.position.is_closer_than(10, self.rendezvous) for unit in self.units):
      completed = True
      self.log("completed because we finished retreating")
    elif self.status == self.manager.enemy_structures.closer_than(5, self.target.position).empty:
      completed = True
      self.log("completed because target location has been successfully cleared")

    return completed

class DefenseObjective(StrategicObjective):
  def __init__(self, manager, urgency=Urgency.HIGH, rendezvous=None):
    super().__init__(manager, urgency, rendezvous)
    self.log("creating defense objective")

  @property
  def target(self):
    return self.enemies.center if self.enemies.exists else self.manager.townhalls.center

  def is_complete(self):
    completed = False
    if self.enemies.empty:
      completed = True
      self.log("Completed because enemies have all been killed or seen elsewhere")
    elif self.manager.time - self.last_seen > 5:
      completed = True
      self.log("Completed because no units have been seen in 5 seconds")
    return completed

  @property
  def enemies(self):
    return Units(
      self.manager.advisor_data.scouting['enemy_army'].values(),
      self.manager
    ).filter(lambda enemy:
      any(nex.position.is_closer_than(25, enemy) for nex in self.manager.townhalls)
    )

  def stage(self):
    self.log("skipping staging because reasons (maybe do something here later, recall or something)")
    self.status = ObjectiveStatus.ACTIVE
    self.status_since = self.manager.time

  def retreat(self):
    pass

  def wanted_units(self):
    return 3 if optimism(self.units, self.enemies) < 3 else 0
