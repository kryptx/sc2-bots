import enum
import itertools

from sc2.constants import UnitTypeId
from sc2.position import Point2
from sc2.units import Units

from modubot.common import optimism, CombatUnits

class ObjectiveStatus(enum.IntFlag):
  ALLOCATING = 1,   # Need more units
  STAGING = 2,      # Getting into position and well-arranged
  ACTIVE = 3,       # Attacking
  RETREATING = 4    # boo

class StrategicObjective():
  def __init__(self, bot, urgency, rendezvous=None):
    self.bot = bot
    self.status = ObjectiveStatus.ALLOCATING
    self.status_since = bot.time
    self.allocated = set()
    self.urgency = urgency
    self.rendezvous = rendezvous
    self.units = Units([], bot)
    self.last_seen = bot.time
    self.enemies = self.find_enemies()

  @property
  def target(self):
    raise NotImplementedError("You must extend this class and provide a target property")

  def log(self, msg):
    print(f"{type(self).__name__} {msg}")

  def is_complete(self):
    if self.bot.time - self.last_seen > 5:
      self.log("completed: enemies have not been seen for 5 seconds")
      if self.status == ObjectiveStatus.ACTIVE:
        # any enemies still in self.enemies should be removed from the enemy army
        # there probably aren't many but they are clearly interfering with us at this point
        self.log(f"objective was active; clearing {self.enemies.amount} tags from known enemies!")
        for enemy_tag in (e.tag for e in self.enemies):
          self.bot.shared.known_enemy_units.pop(enemy_tag, None)

      return True
    return False

  def find_enemies(self):
    return (Units(self.bot.shared.known_enemy_units.values(), self.bot) + self.bot.enemy_structures) \
      .filter(lambda u: u.is_visible or not self.bot.is_visible(u.position))

  def abort(self):
    self.status = ObjectiveStatus.RETREATING
    self.status_since = self.bot.time

  async def tick(self):
    self.enemies = self.find_enemies()
    if self.bot.enemy_units.tags_in(e.tag for e in self.enemies).exists:
      self.last_seen = self.bot.time
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
    self.status_since = self.bot.time

  def retreat_unit(self, unit, target):
    if unit.type_id == UnitTypeId.STALKER and unit.weapon_cooldown == 0:
      self.bot.do(unit.attack(target))
    else:
      self.bot.do(unit.move(target))

  def minimum_units(self, enemy_units):
    return 0

  def optimum_units(self, enemy_units):
    return self.bot.units(CombatUnits).amount

  def do_attack(self, unit):
    self.bot.do(unit.attack(self.enemies.closest_to(self.target.position).position if self.enemies.exists else self.target.position))

  async def micro(self):
    if self.units.empty:
      return

    if self.bot.time - self.status_since > 2:
      self.status_since = self.bot.time
      for unit in self.units:
        self.do_attack(unit)

    near_target_units = self.units.closer_than(30, self.target)
    cooling_down_units = near_target_units.filter(lambda u: u.weapon_cooldown > 0)
    if cooling_down_units.amount < near_target_units.amount / 2:
      for unit in cooling_down_units:
        self.bot.do(unit.move(unit.position.towards(self.target, 2)))
        self.bot.do(unit.attack(self.target.position, queue=True))

    nearby_enemies = Units(list({
      enemy_unit
      for (friendly_unit, enemy_unit) in itertools.product(self.units, self.enemies)
      if enemy_unit.position.is_closer_than(8, friendly_unit)
    }), self.bot)
    if nearby_enemies.exists:
      nearby_allies = self.units.closer_than(30, nearby_enemies.center)
      if nearby_allies.amount >= self.units.amount / 3 and \
        self.bot.shared.optimism < 1.5 and optimism(nearby_allies, nearby_enemies) < 0.75:

        self.log(f"*****RETREATING***** {nearby_enemies.amount} enemies, {self.units.amount} units ({nearby_allies.amount} nearby)")
        self.status = ObjectiveStatus.RETREATING
        self.status_since = self.bot.time
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
    usable_units = self.bot.unallocated(CombatUnits, self.urgency)
    if usable_units.amount >= still_needed:
      adding_units = set(unit.tag for unit in usable_units.closest_n_units(self.target.position, still_wanted))
      self.bot.deallocate(adding_units)
      self.allocated = self.allocated.union(adding_units)
      if len(self.allocated) >= minimum_units:
        may_proceed = True

    if may_proceed:
      if self.status == ObjectiveStatus.ALLOCATING:
        # self.log("approved for staging")
        self.status = ObjectiveStatus.STAGING
        self.status_since = self.bot.time

    self.units = self.bot.units.tags_in(self.allocated)
    # noisy, but possibly informative
    # self.log(f"{self.units.amount} units allocated for {self.enemies.amount} known enemies")
    return