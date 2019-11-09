from sc2.constants import UnitTypeId, BuffId, AbilityId

from modubot.common import TrainingRequest, StructureRequest, Urgency
from modubot.modules.module import BotModule

class LarvaInjector(BotModule):
  def __init__(self, bot):
    super().__init__(bot)
    self.queens = set()

  @property
  def allocated(self):
    return self.queens

  @property
  def urgency(self):
    return Urgency.HIGH

  async def on_step(self, iteration):
    requests = []
    self.queens = self.queens.union({ q.tag for q in self.unallocated(UnitTypeId.QUEEN, self.urgency) })
    queens = self.units(UnitTypeId.QUEEN)

    bases = self.structures(self.shared.base_types)
    queen_urgency = Urgency.NONE
    if queens.amount < bases.amount:
      queen_urgency = Urgency.HIGH
    elif queens.amount < bases.amount + 1:
      queen_urgency = Urgency.LOW

    requests.append(TrainingRequest(UnitTypeId.QUEEN, queen_urgency))

    ready_queens = self.units(UnitTypeId.QUEEN).filter(lambda q: q.energy > 25)
    needy_bases = self.structures(self.shared.base_types).filter(lambda s: not s.has_buff(BuffId.QUEENSPAWNLARVATIMER))

    for i in range(min(needy_bases.amount, ready_queens.amount)):
      def distance_to_closest_queen(base):
        return base.distance_to(ready_queens.closest_to(base.position))

      base_with_closest_queen = max(needy_bases, key=distance_to_closest_queen)
      selected_queen = ready_queens.closest_to(base_with_closest_queen)
      self.do(selected_queen(AbilityId.EFFECT_INJECTLARVA, base_with_closest_queen))
      needy_bases = needy_bases.filter(lambda b: b != base_with_closest_queen)
      ready_queens = ready_queens.filter(lambda q: q != selected_queen)

    return requests
