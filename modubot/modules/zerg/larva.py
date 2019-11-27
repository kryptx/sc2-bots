from sc2.constants import UnitTypeId, BuffId, AbilityId

from modubot.common import BuildRequest, Urgency
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

  def deallocate(self, tag_set):
    self.queens.difference_update(tag_set)

  async def on_step(self, iteration):
    requests = []
    self.queens = self.queens.union({ q.tag for q in self.unallocated(UnitTypeId.QUEEN, self.urgency) })
    queens = self.units(UnitTypeId.QUEEN)

    bases = self.townhalls
    queen_urgency = Urgency.NONE
    queen_count = queens.amount + self.already_pending(UnitTypeId.QUEEN)
    if queen_count < bases.amount:
      queen_urgency = Urgency.HIGH
    elif queens.amount < bases.amount + 1:
      queen_urgency = Urgency.LOW

    requests.append(BuildRequest(UnitTypeId.QUEEN, queen_urgency))

    ready_queens = self.units.tags_in(self.queens).filter(lambda q:
      q.energy >= 25 and not q.is_using_ability({
        AbilityId.EFFECT_INJECTLARVA,
        AbilityId.BUILD_CREEPTUMOR_QUEEN
      })
    )

    busy_queens = self.units(UnitTypeId.QUEEN).filter(lambda q: not q.is_idle)

    needy_bases = self.townhalls.ready.filter(lambda s:
      not s.has_buff(BuffId.QUEENSPAWNLARVATIMER) and busy_queens.filter(lambda q: q.orders[0].target == s.tag).empty)

    for i in range(min(needy_bases.amount, ready_queens.amount)):
      def distance_to_closest_queen(base):
        return base.distance_to(ready_queens.closest_to(base.position))

      base_with_closest_queen = min(needy_bases, key=distance_to_closest_queen)

      if busy_queens.filter(lambda q: q.order_target == base_with_closest_queen and q.is_using_ability(AbilityId.EFFECT_INJECTLARVA)).empty:
        selected_queen = ready_queens.closest_to(base_with_closest_queen)
        self.do(selected_queen(AbilityId.EFFECT_INJECTLARVA, base_with_closest_queen))
      needy_bases = needy_bases.filter(lambda b: b != base_with_closest_queen)
      ready_queens = ready_queens.filter(lambda q: q != selected_queen)

    return requests
