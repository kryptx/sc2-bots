import enum
import itertools
import logging
import math

from sc2.constants import UnitTypeId
from sc2.position import Point2
from sc2.units import Units

from modubot.common import optimism, is_worker, median_position

class ObjectiveStatus(enum.IntFlag):
  ALLOCATING = 1,   # Need more units
  STAGING = 2,      # Getting into position and well-arranged
  ACTIVE = 3,       # Attacking
  RETREATING = 4    # boo

class StrategicObjective():
  def __init__(self, module, urgency, rendezvous=None):
    self.module = module
    self.bot = module.bot
    self.status = ObjectiveStatus.ALLOCATING
    self.status_since = self.bot.time
    self.allocated = set()
    self.urgency = urgency
    self.rendezvous = rendezvous
    self.units = Units([], self.bot)
    self.last_seen = self.bot.time
    self.enemies = self.find_enemies()
    self.log = module.log.withFields({"objective": type(self).__name__ })

  def __getattr__(self, name):
    return getattr(self.bot, name)

  @property
  def target(self):
    raise NotImplementedError("You must extend this class and provide a target property")

  def is_complete(self):
    if self.time - self.last_seen > 5:
      self.log.info("completed: enemies have not been seen for 5 seconds")
      if self.status == ObjectiveStatus.ACTIVE:
        # any enemies still in self.enemies should be removed from the enemy army
        # there probably aren't many but they are clearly interfering with us at this point
        self.log.info(f"objective was active; clearing {self.enemies.amount} tags from known enemies!")
        for enemy_tag in (e.tag for e in self.enemies):
          self.shared.known_enemy_units.pop(enemy_tag, None)

      return True
    return False

  def find_enemies(self):
    return (Units(self.shared.known_enemy_units.values(), self.bot) + self.enemy_structures) \
      .filter(lambda u: u.is_visible or not self.is_visible(u.position))

  def abort(self):
    self.status = ObjectiveStatus.RETREATING
    self.status_since = self.time

  async def tick(self):
    self.log.info({
      "status": self.status,
      "num_units": self.units.amount,
      "num_enemies": self.enemies.amount,
      "game_time": self.time,
    })
    self.enemies = self.find_enemies()
    if self.enemy_units.tags_in(e.tag for e in self.enemies).exists:
      self.last_seen = self.time
    if self.status >= ObjectiveStatus.ALLOCATING:
      self.allocate()
    if self.status == ObjectiveStatus.STAGING:
      self.stage()
    if self.status == ObjectiveStatus.ACTIVE:
      await self.micro()
    if self.status == ObjectiveStatus.RETREATING:
      await self.retreat()

  # retreat requires implementation in subclasses
  # [ Really tricky on defense. For now, victory or death! ]
  async def retreat(self):
    await self.micro()

  def stage(self):
    # override this if you want to stage units
    self.status = ObjectiveStatus.ACTIVE
    self.status_since = self.time

  def retreat_unit(self, unit, target):
    if unit.ground_range >= 5 and unit.weapon_cooldown == 0:
      self.do(unit.attack(target))
    else:
      self.do(unit.move(target))

  def minimum_units(self, enemy_units):
    return 0

  def optimum_units(self, enemy_units):
    return self.bot.units.filter(lambda u: u.ground_dps + u.air_dps > 5 and not is_worker(u)).amount

  def do_attack(self, unit):
    self.do(unit.attack(self.enemies.closest_to(self.target.position).position if self.enemies.exists else self.target.position))

  async def micro(self):
    self.rendezvous = None
    if self.units.empty:
      return

    if self.time - self.status_since > 2:
      self.status_since = self.time
      for unit in self.units:
        self.do_attack(unit)

    near_target_units = self.units.closer_than(15, self.target)
    cooling_down_units = near_target_units.filter(lambda u: u.weapon_cooldown > 0)
    if cooling_down_units.amount < near_target_units.amount / 3:
      for unit in cooling_down_units:
        self.do(unit.move(unit.position.towards(self.target, 2)))
        self.do(unit.attack(self.target.position, queue=True))

    nearby_enemies = Units(list({
      enemy_unit
      for (friendly_unit, enemy_unit) in itertools.product(self.units, self.enemies)
      if enemy_unit.position.is_closer_than(10, friendly_unit)
    }), self.bot)
    if nearby_enemies.exists:
      allies_center = median_position([u.position for u in self.units])
      clustered_allies = self.units.closer_than(15, allies_center)
      if optimism(clustered_allies, self.enemies) < 0.75 and self.supply_used < 180:
        self.status = ObjectiveStatus.RETREATING
        self.status_since = self.time
    return

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
    usable_units = self.unallocated(urgency=self.urgency).filter(lambda u: not is_worker(u))
    if enemy_units.filter(lambda e: not e.is_flying).empty:
      usable_units = usable_units.filter(lambda u: u.can_attack_air)
    adding_units = set()

    if usable_units.amount >= still_needed:
      adding_units = set(u.tag for u in usable_units.closest_n_units(self.target.position, still_wanted))

    self.deallocate(adding_units)
    self.allocated = self.allocated.union(adding_units)

    if len(self.allocated) >= minimum_units:
      may_proceed = True

    if may_proceed:
      if self.status == ObjectiveStatus.ALLOCATING:
        self.status = ObjectiveStatus.STAGING
        self.status_since = self.time

      elif self.status == ObjectiveStatus.RETREATING and \
        self.shared.optimism > 1.5 and \
        self.units.exists and \
        self.units.closer_than(15, median_position([u.position for u in self.units])).amount > self.units.amount / 2:
        self.status = ObjectiveStatus.STAGING
        self.status_since = self.time

    self.units = self.bot.units.tags_in(self.allocated)

    if len(adding_units) > 0:
      self.log.debug({
        "message": "Allocating units",
        "quantity": len(adding_units),
        "now_allocated": len(self.allocated),
      })
    # noisy, but possibly informative
    # self.log.info(f"{self.units.amount} units allocated for {self.enemies.amount} known enemies")
    return
