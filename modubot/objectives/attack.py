import itertools

from sc2.constants import UnitTypeId
from sc2.position import Point2

from modubot.common import Urgency, optimism, is_worker, median_position
from modubot.objectives.objective import StrategicObjective, ObjectiveStatus

class AttackObjective(StrategicObjective):
  def __init__(self, module, target, urgency=Urgency.MEDIUM, rendezvous=None):
    super().__init__(module, urgency, rendezvous)
    self._target = target

  @property
  def target(self):
    return self._target

  def minimum_units(self, enemy_units):
    return min(20, int(enemy_units.filter(lambda u: not u.is_structure and not is_worker(u)).amount / 2))

  async def retreat(self):
    for retreating_unit in self.units:
      # if all(retreating_unit.position.is_further_than(10, enemy.position) for enemy in self.enemies):
      #   self.allocated.discard(retreating_unit.tag)
      if retreating_unit.position.is_further_than(10, self.shared.rally_point):
        self.retreat_unit(retreating_unit, self.shared.rally_point)

  def stage(self):
    allocated_units = self.units

    if optimism(allocated_units, self.enemies) > 2.5:
      for attacking_unit in allocated_units:
        self.do(attacking_unit.attack(self.target.position))
      self.log.info("Upgrading to active due to apparent overwhelming advantage")
      self.status = ObjectiveStatus.ACTIVE
      self.status_since = self.time
      return

    if self.time - self.status_since > 2 and any(
      unit.engaged_target_tag in (u.tag for u in allocated_units)
      for unit in self.enemy_units
    ):
      self.log.info("Upgrading to active because staging lasted 2 seconds and we are being attacked")
      self.status = ObjectiveStatus.ACTIVE
      self.status_since = self.time
      return

    if not self.rendezvous:
      middle = median_position([u.position for u in self.units]) if self.units.exists else self.game_info.map_center
      if self.units.closer_than(15, middle).amount < self.units.amount * 0.75:
        for attacking_unit in allocated_units:
          self.retreat_unit(attacking_unit, middle)
        return

      for attacking_unit in allocated_units:
        nearby_enemies = self.enemies.filter(lambda e: e.position.is_closer_than(12, attacking_unit))
        if nearby_enemies.amount > 1:
          front_units = allocated_units.filter(lambda friendly: self.enemies.filter(lambda e: e.position.is_closer_than(12, friendly)).exists)
          next_units = allocated_units.tags_not_in(u.tag for u in front_units)
          next_unit = next_units.closest_to(front_units.center) if next_units.exists else front_units.random
          self.rendezvous = next_unit.position
        elif nearby_enemies.exists and attacking_unit.position.is_further_than(15, middle):
          self.retreat_unit(attacking_unit, middle)
        else:
          self.do(attacking_unit.attack(self.target.position))

    if self.supply_left < 5:
      for attacking_unit in allocated_units:
        self.do(attacking_unit.attack(self.target.position))
      self.log.info("Upgrading to active due to nearing supply cap")
      self.status = ObjectiveStatus.ACTIVE
      self.status_since = self.time

    if not self.rendezvous:
      return

    if allocated_units.closer_than(10, self.rendezvous).amount > allocated_units.amount * 0.75:
      for attacking_unit in allocated_units:
        self.do(attacking_unit.attack(self.target.position))
      self.log.info("Upgrading to active after at least 75% of units arrived at rendezvous")
      self.status = ObjectiveStatus.ACTIVE
      self.status_since = self.time
      return

    if self.enemy_units.closer_than(8, self.rendezvous).amount > 3:
      for attacking_unit in allocated_units:
        self.do(attacking_unit.attack(self.target.position))
      self.log.info("Upgrading to active due to enemy units at rendezvous")
      self.status = ObjectiveStatus.ACTIVE
      self.status_since = self.time

    for attacking_unit in allocated_units:
      self.do(attacking_unit.move(self.rendezvous.towards(self.target.position, 3 - attacking_unit.ground_range)))

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
      # self.log.info("completed (cancelled): no units allocated")
    elif self.status == ObjectiveStatus.RETREATING and all(unit.position.is_closer_than(15, self.shared.rally_point) for unit in self.units):
      completed = True
      self.log.info("completed: we finished retreating")
    elif self.is_visible(self.target.position) and (self.enemy_structures + self.enemy_units).visible.closer_than(10, self.target.position).empty:
      completed = True
      self.log.info("completed: target location has been successfully cleared")

    return completed

  def do_attack(self, unit):
    targets = self.enemy_units + self.enemy_structures
    if targets.exists:
      self.do(unit.attack(targets.closest_to(self.target).position))
    else:
      self.do(unit.attack(self.target))
