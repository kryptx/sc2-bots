from sc2.constants import UnitTypeId
from sc2.units import Units

from modubot.common import Urgency, optimism, supply_cost

from modubot.objectives.objective import StrategicObjective, ObjectiveStatus

class DefenseObjective(StrategicObjective):
  def __init__(self, module, urgency=Urgency.VERYHIGH, rendezvous=None):
    super().__init__(module, urgency, rendezvous)

  @property
  def target(self):
    return self.enemies.center if self.enemies.exists \
      else self.townhalls.center if self.townhalls.exists \
      else self.structures.center

  def allocate(self):
    super().allocate()
    # get workers if needed
    mission_optimism = optimism(self.units, self.enemies)
    if mission_optimism < 1 and self.enemies.amount > 3 and any(not e.is_flying for e in self.enemies):
      nearby_workers = self.unallocated(self.shared.worker_types).closer_than(20, self.enemies.center)
      if nearby_workers.exists:
        adding_units = set(worker.tag for worker in nearby_workers)
        self.deallocate(adding_units)
        self.allocated = self.allocated.union(adding_units)
        self.units = self.bot.units.tags_in(self.allocated)
    # release units immediately when enemies have left
    # this will allow probes to return to work
    # and army units to be reallocated or brought to rally
    elif self.enemies.empty:
      self.allocated.clear()
      self.units = Units([], self.bot)

    if all(e.is_flying for e in self.enemies):
      self.deallocate({ u.tag for u in self.units if not u.can_attack_air })

  def is_complete(self):
    completed = super().is_complete()
    if completed:
      return completed
    elif self.enemies.empty:
      completed = True
      self.log.info("completed: enemies have all been killed or gone")

    return completed

  def find_enemies(self):
    return Units(self.shared.known_enemy_units.values(), self.bot).filter(lambda u:
      (self.townhalls.closer_than(15, u.position).exists or
      self.shared.rally_point.is_closer_than(15, u.position) or
      self.structures.closer_than(15, u.position).amount > 2)
    )

  def optimum_supply(self, enemy_units):
    return sum(supply_cost(u) for u in enemy_units) * 3
