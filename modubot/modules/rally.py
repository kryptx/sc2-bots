from .module import BotModule
from modubot.common import retreat

class RallyPointer(BotModule):
  def __init__(self, bot):
    super().__init__(bot)
    bot.shared.rally_point = None

  async def on_step(self, iteration):
    self.shared.rally_point = self.determine_rally_point()

    if not self.shared.rally_point:
      return

    for unit in self.unallocated().further_than(15, self.shared.rally_point):
      self.do(retreat(unit, self.shared.rally_point))

    destructables = self.destructables.filter(lambda d: d.position.is_closer_than(10, self.shared.rally_point))
    if destructables.exists:
      for unit in self.unallocated().idle:
        self.do(unit.attack(destructables.first))

  def determine_rally_point(self):
    if self.townhalls.empty or self.townhalls.amount == 1:
      return list(self.main_base_ramp.upper)[0]

    def distance_to_bases(ramp):
      return ramp.top_center.distance_to(self.bases_centroid().towards(self.game_info.map_center, 20))

    ramps = sorted(self.game_info.map_ramps, key=distance_to_bases)
    return list(ramps[0].upper)[0]
