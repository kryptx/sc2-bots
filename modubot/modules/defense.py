import sc2
from sc2.position import Point2
from sc2.units import Units

from .module import BotModule
from modubot.common import list_flatten, Urgency
from modubot.objectives.objective import ObjectiveStatus
from modubot.objectives.defense import DefenseObjective

class DefendBases(BotModule):
  def __init__(self, bot):
    super().__init__(bot)
    self.defense_objective = None
    bot.shared.defenders = Units([], bot)
    bot.shared.threats = Units([], bot)

  async def on_unit_destroyed(self, unit):
    self.allocated.discard(unit)

  async def on_step(self, iteration):
    self.shared.defenders = self.units.tags_in(self.allocated)

    if self.defense_objective:
      await self.defense_objective.tick()
      if self.defense_objective.is_complete():
        self.shared.threats = Units([], self.bot)
        self.defense_objective = None
      else:
        self.shared.threats = self.defense_objective.enemies
        return

    #enemies within 20 units of at least 2 of my structures
    # or, within 15 of the rally point
    threatening_enemies = self.enemy_units.filter(lambda enemy:
      not enemy.is_snapshot and (
        self.townhalls.closer_than(20, enemy.position).exists or
        self.structures.closer_than(20, enemy.position).amount > 2 or
        enemy.position.is_closer_than(20, self.shared.rally_point)
      )
    )

    if threatening_enemies.exists:
      self.defense_objective = DefenseObjective(self)

  @property
  def allocated(self):
    return self.defense_objective.allocated if self.defense_objective else set()

  @property
  def urgency(self):
    return Urgency.VERYHIGH

  def deallocate(self, tag_set):
    if self.defense_objective:
      self.defense_objective.allocated.difference_update(tag_set)
