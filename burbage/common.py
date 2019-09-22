import asyncio
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
  return (sum(u.ground_dps * (u.health + u.shield) * (2 if u.is_massive else 1) for u in units) + 100) / (sum(u.ground_dps * (u.health + u.shield) * (2 if u.is_massive else 1) for u in enemy_units) + 100)

def dps(units):
  return sum(u.ground_dps for u in units)

def max_hp(units):
  return sum(u.health_max + u.shield_max for u in units)

def retreat(unit, target):
  return unit.attack(target.position) if unit.weapon_cooldown == 0 else unit.move(target.position)


class StrategicObjective():
  def __init__(self, manager, urgency, rendezvous=None):
    self.manager = manager
    self.status = ObjectiveStatus.ALLOCATING
    self.status_since = manager.time
    self.allocated = set()
    self.urgency = urgency
    self.rendezvous = rendezvous
    self.units = Units([], manager)
    self.last_seen = manager.time
    self.enemies = self.find_enemies()

  def log(self, msg):
    print(f"{type(self).__name__} {msg}")

  def is_complete(self):
    if self.manager.time - self.last_seen > 5:
      self.log("completed: enemies have not been seen for 5 seconds")
      if self.status == ObjectiveStatus.ACTIVE:
        # any enemies still in self.enemies should be removed from the enemy army
        # there probably aren't many but they are clearly interfering with us at this point
        for enemy_tag in (e.tag for e in self.enemies):
          self.manager.advisor_data.scouting['enemy_army'].pop(enemy_tag, None)

      return True
    return False

  def find_enemies(self):
    return (Units(self.manager.advisor_data.scouting['enemy_army'].values(), self.manager) + self.manager.enemy_structures) \
      .filter(lambda u: u.is_visible or not self.manager.is_visible(u.position))

  def abort(self):
    self.status = ObjectiveStatus.RETREATING
    self.status_since = self.manager.time

  async def tick(self):
    self.enemies = self.find_enemies()
    if self.manager.enemy_units.tags_in(e.tag for e in self.enemies).exists:
      self.last_seen = self.manager.time
    if self.status >= ObjectiveStatus.ALLOCATING:
      self.allocate()
    if self.status == ObjectiveStatus.STAGING:
      self.stage()
    if self.status == ObjectiveStatus.ACTIVE:
      await self.micro()
    if self.status == ObjectiveStatus.RETREATING:
      await self.retreat()

  def retreat_unit(self, unit, target):
    if unit.type_id == UnitTypeId.STALKER and unit.weapon_cooldown == 0:
      self.manager.do(unit.attack(target))
    else:
      self.manager.do(unit.move(target))

  def minimum_units(self, enemy_units):
    return 0

  def optimum_units(self, enemy_units):
    return self.manager.units(CombatUnits).amount

  def do_attack(self, unit):
    self.manager.do(unit.attack(self.enemies.closest_to(self.target.position).position if self.enemies.exists else self.target.position))

  async def micro(self):
    if self.units.empty:
      self.log("no units to micro")
      return

    if self.manager.time - self.status_since > 2:
      self.status_since = self.manager.time
      for unit in self.units:
        self.do_attack(unit)

    near_target_units = self.units.closer_than(30, self.target)
    cooling_down_units = near_target_units.filter(lambda u: u.weapon_cooldown > 0)
    if cooling_down_units.amount < near_target_units.amount / 2:
      for unit in cooling_down_units:
        self.manager.do(unit.move(unit.position.towards(self.target, 2)))
        self.manager.do(unit.attack(self.target.position, queue=True))

    nearby_enemies = Units(list({
      enemy_unit
      for (friendly_unit, enemy_unit) in itertools.product(self.units, self.enemies)
      if enemy_unit.position.is_closer_than(8, friendly_unit)
    }), self.manager)
    if nearby_enemies.exists:
      nearby_allies = self.units.closer_than(30, nearby_enemies.center)
      if nearby_allies.amount >= self.units.amount / 3 and self.manager.strategy_advisor.optimism < 1.5 and optimism(nearby_allies, nearby_enemies) < 0.75:
        self.log(f"*****RETREATING***** {nearby_enemies.amount} enemies, {self.units.amount} units ({nearby_allies.amount} nearby)")
        self.status = ObjectiveStatus.RETREATING
        self.status_since = self.manager.time
    return

  async def retreat(self):
    self.rendezvous = Point2.center([ self.manager.rally_point, self.units.center if self.units.exists else self.manager.game_info.map_center ])
    for retreating_unit in self.units:
      if retreating_unit.position.is_further_than(5, self.rendezvous):
        self.retreat_unit(retreating_unit, Point2.center([ self.units.center, self.rendezvous ]))

    if self.units.empty:
      return

    grouped_fighters = self.units.closer_than(10, self.units.center)
    local_opt = optimism(grouped_fighters, self.enemies) if grouped_fighters.exists else 0
    if local_opt > 3 and grouped_fighters.amount >= self.enemies.amount:
      print(f"Returning to active because local optimism is {local_opt}")
      self.status = ObjectiveStatus.ACTIVE
      self.status_since = self.manager.time
    elif all(unit.position.is_closer_than(10, self.rendezvous) for unit in self.units):
      self.allocated.clear()

  def stage(self):
    allocated_units = self.units

    if allocated_units.amount > self.enemies.amount * 6:
      for attacking_unit in allocated_units:
        self.manager.do(attacking_unit.attack(self.target.position))
      self.log("Upgrading to active due to apparent overwhelming advantage")
      self.status = ObjectiveStatus.ACTIVE
      self.status_since = self.manager.time
      return

    if self.manager.time - self.status_since > 2 and any(
      unit.engaged_target_tag in (u.tag for u in allocated_units)
      for unit in self.manager.enemy_units
    ):
      self.log("Upgrading to active because staging lasted 2 seconds and we are being attacked")
      self.status = ObjectiveStatus.ACTIVE
      self.status_since = self.manager.time
      return

    if not self.rendezvous:
      for attacking_unit in allocated_units:
        self.manager.do(attacking_unit.attack(self.target.position))
      if any(enemy.position.is_closer_than(10, friendly) for (enemy, friendly) in itertools.product(self.manager.enemy_units + self.manager.enemy_structures, allocated_units)):
        self.rendezvous = allocated_units.center

    if not self.rendezvous:
      return

    if allocated_units.closer_than(10, self.rendezvous).amount > allocated_units.amount * 0.75:
      for attacking_unit in allocated_units:
        self.manager.do(attacking_unit.attack(self.target.position))
      self.log("Upgrading to active after at least 75% of units arrived at rendezvous")
      self.status = ObjectiveStatus.ACTIVE
      self.status_since = self.manager.time
      return

    if self.manager.enemy_units.closer_than(15, self.rendezvous).amount > 3:
      for attacking_unit in allocated_units:
        self.manager.do(attacking_unit.attack(self.target.position))
      self.log("Upgrading to active due to enemy units at rendezvous")
      self.status = ObjectiveStatus.ACTIVE
      self.status_since = self.manager.time

    for attacking_unit in allocated_units:
      if attacking_unit.type_id == UnitTypeId.STALKER:
        self.manager.do(attacking_unit.move(self.rendezvous.towards(self.target.position, -3)))
      elif attacking_unit.type_id == UnitTypeId.ZEALOT:
        self.manager.do(attacking_unit.move(self.rendezvous.towards(self.target.position, 3)))
      elif attacking_unit.type_id == UnitTypeId.ARCHON:
        self.manager.do(attacking_unit.move(self.rendezvous))

  def allocate(self):
    may_proceed = False
    enemy_units = self.enemies
    minimum_units = self.minimum_units(enemy_units)
    optimum_units = self.optimum_units(enemy_units)
    allocated_units = len(self.allocated)

    if minimum_units <= allocated_units:
      may_proceed = True

    still_needed = minimum_units - allocated_units
    still_wanted = optimum_units - allocated_units
    usable_units = self.manager.unallocated(CombatUnits, self.urgency)
    if usable_units.amount >= still_needed:
      adding_units = set(unit.tag for unit in usable_units.closest_n_units(self.target.position, still_wanted))
      for objective in self.manager.strategy_advisor.objectives:
        objective.allocated.difference_update(adding_units)
      self.allocated = self.allocated.union(adding_units)
      if len(self.allocated) >= minimum_units:
        may_proceed = True

    if may_proceed:
      if self.status == ObjectiveStatus.ALLOCATING:
        self.log("approved for staging")
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

  def minimum_units(self, enemy_units):
    return min(20, int(enemy_units.filter(lambda u: not u.is_structure).amount))

  def is_complete(self):
    completed = super().is_complete()
    if completed:
      return completed
    elif self.units.empty:
      completed = True
      # noisy, and probably not all that useful
      # it'll create an attack objective every frame if optimism is high enough and units are allocated to defense
      # They naturally get cancelled because they can't allocate sufficient units
      # Possibly in the future, enemies for attack objectives should exclude those in defense objectives
      # self.log("completed (cancelled): no units allocated")
    elif self.status == ObjectiveStatus.RETREATING and all(unit.position.is_closer_than(15, self.rendezvous) for unit in self.units):
      completed = True
      self.log("completed: we finished retreating")
    elif (self.manager.enemy_structures + self.manager.enemy_units).closer_than(10, self.target.position).empty:
      completed = True
      self.log("completed: target location has been successfully cleared")

    return completed

  def do_attack(self, unit):
    self.manager.do(unit.attack((self.manager.enemy_units + self.manager.enemy_structures).closest_to(self.target).position))

class DefenseObjective(StrategicObjective):
  def __init__(self, manager, urgency=Urgency.HIGH, rendezvous=None):
    super().__init__(manager, urgency, rendezvous)
    self.log("creating defense objective")

  @property
  def target(self):
    return self.enemies.center if self.enemies.exists \
      else self.manager.townhalls.center if self.manager.townhalls.exists \
      else self.manager.structures.center

  def is_complete(self):
    completed = super().is_complete()
    if completed:
      return completed
    elif self.enemies.empty:
      completed = True
      self.log("completed: enemies have all been killed or gone")

    return completed

  def find_enemies(self):
    return Units(self.manager.advisor_data.scouting['enemy_army'].values(), self.manager).filter(lambda u:
        (self.manager.structures.closer_than(20, u.position).amount > 1
        or self.manager.rally_point.is_closer_than(15, u.position))
    )

  def optimum_units(self, enemy_units):
    return enemy_units.amount * 2

  def stage(self):
    self.log("skipping staging because reasons (maybe do something here later, recall or something)")
    self.status = ObjectiveStatus.ACTIVE
    self.status_since = self.manager.time

  async def retreat(self):
    await self.micro()
