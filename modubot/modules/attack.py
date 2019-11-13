import sc2
from sc2.position import Point2
from sc2.units import Units

from .module import BotModule
from modubot.common import list_flatten, BaseStructures, Urgency
from modubot.objectives.objective import ObjectiveStatus
from modubot.objectives.attack import AttackObjective

class AttackBases(BotModule):
  def __init__(self, bot):
    super().__init__(bot)
    self.attack_objective = None
    bot.shared.attackers = Units([], bot)
    bot.shared.victims = Units([], bot)

  async def on_unit_destroyed(self, unit):
    # first condition cannot be true unless attack_objective exists
    if unit in self.allocated and self.attack_objective.status == ObjectiveStatus.STAGING:
      self.attack_objective.log.info("Upgrading to active because a unit was killed while staging")
      self.attack_objective.status = ObjectiveStatus.ACTIVE
    self.allocated.discard(unit)

  async def on_step(self, iteration):
    self.shared.attackers = self.units.tags_in(self.allocated)
    if self.attack_objective:
      await self.attack_objective.tick()
      if self.attack_objective.is_complete():
        self.shared.victims = Units([], self.bot)
        self.attack_objective = None
      else:
        self.shared.victims = self.attack_objective.enemies
        return

    if (self.supply_used > 196 or self.shared.optimism > 1.5) and not self.attack_objective:
      known_enemy_units = self.shared.known_enemy_units.values()
      enemy_bases = self.enemy_structures(BaseStructures)
      if enemy_bases.exists:
        self.attack_objective = AttackObjective(
          self.bot,
          enemy_bases.furthest_to(
            Point2.center([ u.position for u in known_enemy_units ]) if known_enemy_units
            else self.enemy_start_locations[0]
          ).position
        )
      elif self.enemy_structures.exists:
        self.attack_objective = AttackObjective(self.bot, self.enemy_structures.closest_to(self.units.center).position)
      else:
        self.attack_objective = AttackObjective(self.bot, self.enemy_start_locations[0])

  @property
  def allocated(self):
    return self.attack_objective.allocated if self.attack_objective else set()

  @property
  def urgency(self):
    return Urgency.MEDIUM

  def deallocate(self, tag_set):
    if self.attack_objective:
      self.attack_objective.allocated.difference_update(tag_set)
