from sc2.constants import UnitTypeId
from sc2.units import Units

from modubot.common import Urgency, optimism

from modubot.objectives.objective import StrategicObjective, ObjectiveStatus

class DefenseObjective(StrategicObjective):
  def __init__(self, bot, urgency=Urgency.HIGH, rendezvous=None):
    super().__init__(bot, urgency, rendezvous)

  @property
  def target(self):
    return self.enemies.center if self.enemies.exists \
      else self.townhalls.center if self.townhalls.exists \
      else self.structures.center

  def allocate(self):
    super().allocate()
    # get workers if needed
    mission_optimism = optimism(self.units, self.enemies)
    if mission_optimism < 1 and self.enemies.amount > 2:
      nearby_workers = self.unallocated(UnitTypeId.PROBE).closer_than(20, self.enemies.center)
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
        (self.structures.closer_than(20, u.position).amount > 1
        or self.shared.rally_point.is_closer_than(15, u.position))
    )

  def optimum_units(self, enemy_units):
    return enemy_units.amount * 2

